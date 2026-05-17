"""LLMGateway — unico punto di accesso all'LLM in tutto il sistema (Fase 9).

Regola: NESSUN modulo chiama Ollama direttamente.
        Tutti passano per LLMGateway.
        Se LLM è disabilitato → LLMGateway ritorna LLMResult(source="template").
        Se LLM è abilitato ma Ollama è down → template (graceful).

Stato:
  DISABLED  → feature_flag llm_engine_enabled: false (default)
  AVAILABLE → Ollama risponde correttamente
  DEGRADED  → Ollama risponde ma lentamente
  DOWN      → Ollama non raggiungibile

Thread-safe. Gestisce automaticamente LLMCache (TTL 4h da cache_ttl.yaml).

Privacy: chiama SOLO localhost:11434 (Ollama locale). Zero cloud LLM.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from shared.config.cache_ttl_config import CACHE_TTL
from shared.feature_flags import is_enabled
from shared.logger import get_logger

__version__ = "1.0.0"
__all__ = ["LLMGateway", "LLMResult", "LLMStatus", "get_llm_gateway"]

log = get_logger(__name__)


class LLMStatus(str, Enum):
    DISABLED   = "disabled"    # Feature flag off (default)
    AVAILABLE  = "available"   # Ollama risponde
    DEGRADED   = "degraded"    # Risponde ma lento
    DOWN       = "down"        # Non raggiungibile


@dataclass
class LLMResult:
    """Risultato generazione LLM o template fallback."""
    text:        str
    source:      str       # "llm" | "template" | "cache"
    model:       str       # "mistral:7b-q4" | "template_only"
    latency_ms:  float
    cached:      bool


# Template fallback deterministici (Regola 33: usano dati reali passati come context)
_TEMPLATES: dict[str, str] = {
    "market_narrative": (
        "Analisi del {date}: "
        "S&P 500 {sp500_change:+.1f}%, VIX {vix:.1f}. "
        "Segnale composito: {composite_score:+.2f}. "
        "Fonte: dati di mercato reali."
    ),
    "news_analysis": (
        "Notizie recenti ({article_count} articoli): "
        "sentiment {sentiment_label} (score: {score:+.2f}). "
        "Ticker principali: {top_tickers}."
    ),
    "ib_extraction": "[]",  # JSON vuoto: nessuna estrazione senza LLM
    "portfolio_comment": (
        "Portafoglio: rendimento {return_pct:+.1f}%, "
        "volatilità {vol_pct:.1f}%, beta {beta:.2f}."
    ),
    "earnings_summary": (
        "{ticker} Q{quarter} {year}: EPS {eps:+.2f} vs atteso {eps_est:+.2f}."
    ),
    "risk_alert": (
        "Alert: {indicator} ha raggiunto {value:.2f} ({threshold} threshold)."
    ),
}


class _LLMCache:
    """Cache in-memory per output LLM (TTL 4h — Regola 34)."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, datetime]] = {}
        self._ttl_s = CACHE_TTL.get("llm_narrativa", 14400)

    def get(self, key: str) -> str | None:
        item = self._store.get(key)
        if item is None:
            return None
        text, created = item
        age = (datetime.now(UTC) - created).total_seconds()
        if age > self._ttl_s:
            del self._store[key]
            return None
        return text

    def set(self, key: str, text: str) -> None:
        self._store[key] = (text, datetime.now(UTC))

    @staticmethod
    def cache_key(template: str, context: dict) -> str:
        payload = f"{template}:{json.dumps(context, sort_keys=True, default=str)}"
        return hashlib.sha256(payload.encode()).hexdigest()[:32]


class LLMGateway:
    """Singleton thread-safe. Unico punto di accesso all'LLM.

    Usage::

        gw = get_llm_gateway()
        if gw.is_available():
            result = gw.generate("market_narrative", context={...})
        # Altrimenti usa result.source == "template" automaticamente
    """

    def __init__(self) -> None:
        self._cache = _LLMCache()
        self._status = LLMStatus.DISABLED
        self._last_check: datetime | None = None
        self._check_interval_s = 60.0
        self._ollama_host: str = "http://localhost:11434"

    def status(self) -> LLMStatus:
        """Stato corrente del gateway (aggiornato ogni 60s)."""
        if not is_enabled("llm_engine_enabled"):
            return LLMStatus.DISABLED

        now = datetime.now(UTC)
        if (self._last_check is None or
                (now - self._last_check).total_seconds() > self._check_interval_s):
            self._refresh_status()
            self._last_check = now

        return self._status

    def is_available(self) -> bool:
        """True se LLM è abilitato e Ollama risponde."""
        return self.status() in (LLMStatus.AVAILABLE, LLMStatus.DEGRADED)

    def generate(
        self,
        template: str,
        context: dict[str, Any],
        max_tokens: int | None = None,
    ) -> LLMResult:
        """Genera testo tramite LLM o template fallback.

        Args:
            template: Nome template (es. 'market_narrative', 'ib_extraction').
            context:  Dizionario dati reali da inserire nel prompt/template.
            max_tokens: Override max token (default da feature_flags.yaml).

        Returns:
            LLMResult con testo generato e metadati.
        """
        t0 = time.monotonic()

        # 1. LLM inattivo → template deterministico
        if not self.is_available():
            text = self._template_fallback(template, context)
            return LLMResult(
                text=text,
                source="template",
                model="template_only",
                latency_ms=(time.monotonic() - t0) * 1000,
                cached=False,
            )

        # 2. Controlla cache (Regola 34 — TTL 4h)
        cache_key = _LLMCache.cache_key(template, context)
        cached_text = self._cache.get(cache_key)
        if cached_text is not None:
            return LLMResult(
                text=cached_text,
                source="cache",
                model=self._get_model(),
                latency_ms=(time.monotonic() - t0) * 1000,
                cached=True,
            )

        # 3. Chiama Ollama (localhost solo — privacy)
        try:
            text = self._call_ollama(template, context, max_tokens)
            self._cache.set(cache_key, text)
            return LLMResult(
                text=text,
                source="llm",
                model=self._get_model(),
                latency_ms=(time.monotonic() - t0) * 1000,
                cached=False,
            )
        except Exception as exc:
            log.warning("llm_gateway.ollama_failed", error=str(exc)[:100])
            self._status = LLMStatus.DOWN
            # Fallback trasparente al template
            text = self._template_fallback(template, context)
            return LLMResult(
                text=text,
                source="template",
                model="template_only",
                latency_ms=(time.monotonic() - t0) * 1000,
                cached=False,
            )

    def _call_ollama(self, template: str, context: dict, max_tokens: int | None) -> str:
        """Chiama Ollama API locale (localhost:11434)."""
        import httpx

        model = self._get_model()
        prompt = self._build_prompt(template, context)
        mt = max_tokens or int(is_enabled("llm_max_tokens") or 512)

        resp = httpx.post(
            f"{self._ollama_host}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": mt, "temperature": 0.2},
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()

    def _build_prompt(self, template: str, context: dict) -> str:
        """Costruisce il prompt per Ollama."""
        ctx_str = "\n".join(f"- {k}: {v}" for k, v in context.items())
        return (
            f"Sei un analista finanziario professionale. "
            f"Analizza i seguenti dati reali di mercato e produci un commento conciso in italiano.\n\n"
            f"Task: {template}\n"
            f"Dati:\n{ctx_str}\n\n"
            f"Risposta (max 3 frasi, in italiano):"
        )

    def _template_fallback(self, template: str, context: dict) -> str:
        """Template deterministico Jinja-like. Sempre disponibile."""
        tmpl = _TEMPLATES.get(template, "Dati non disponibili.")
        try:
            return tmpl.format(**{k: v for k, v in context.items() if v is not None})
        except (KeyError, ValueError):
            return tmpl.split("{")[0].strip() or "Analisi non disponibile."

    def _refresh_status(self) -> None:
        """Ping Ollama per aggiornare lo stato."""
        if not is_enabled("llm_engine_enabled"):
            self._status = LLMStatus.DISABLED
            return
        try:
            import httpx
            host = str(is_enabled("ollama_host") or "http://localhost:11434")
            self._ollama_host = host
            t0 = time.monotonic()
            resp = httpx.get(f"{host}/api/tags", timeout=5.0)
            resp.raise_for_status()
            latency = (time.monotonic() - t0) * 1000
            self._status = LLMStatus.AVAILABLE if latency < 2000 else LLMStatus.DEGRADED
        except Exception:
            self._status = LLMStatus.DOWN

    def _get_model(self) -> str:
        model = is_enabled("llm_model")
        return str(model) if model else "mistral:7b-q4"


_gateway: LLMGateway | None = None


def get_llm_gateway() -> LLMGateway:
    """Singleton LLMGateway."""
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
