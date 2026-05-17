"""Narrative Generator — commento testuale su dati di mercato.

Integrazione LLM latente (Fase 9):
  LLM attivo  → narrativa fluente in italiano via LLMGateway
  LLM inattivo → template deterministico strutturato (sempre corretto)
"""
from __future__ import annotations

from typing import Any

from shared.logger import get_logger

__version__ = "1.0.0"
__all__ = ["NarrativeGenerator"]

log = get_logger(__name__)


class NarrativeGenerator:
    """Genera commenti testuali su regime, VIX e dati macro.

    Usa LLMGateway con pattern latente: funziona sempre con template,
    migliora automaticamente quando llm_engine_enabled=true.
    """

    def __init__(self) -> None:
        from shared.llm.llm_gateway import get_llm_gateway
        self._llm = get_llm_gateway()

    def generate_market_narrative(self, context: dict[str, Any]) -> str:
        """Genera narrativa mercato giornaliera.

        Args:
            context: Dict con regime, vix, composite_score, macro_summary, news_score.

        Returns:
            Stringa narrativa (da LLM o template).
        """
        try:
            from shared.feature_flags import is_enabled
            if is_enabled("llm_engine_enabled") and is_enabled("llm_narrative_generator") \
                    and self._llm.is_available():
                result = self._llm.generate(
                    template="market_narrative",
                    context=context,
                    max_tokens=512,
                )
                log.debug("narrative.llm_used", latency_ms=result.latency_ms)
                return result.text
        except Exception as exc:
            log.debug("narrative.llm_fallback", error=str(exc)[:80])

        return self._template_fallback(context)

    def generate_portfolio_comment(self, context: dict[str, Any]) -> str:
        """Genera commento portafoglio personalizzato.

        Args:
            context: Dict con total_value, pnl_pct, top_positions, risk_metrics.

        Returns:
            Commento testuale (da LLM o template).
        """
        try:
            from shared.feature_flags import is_enabled
            if is_enabled("llm_engine_enabled") and is_enabled("llm_portfolio_comment") \
                    and self._llm.is_available():
                result = self._llm.generate(
                    template="portfolio_comment",
                    context=context,
                    max_tokens=256,
                )
                return result.text
        except Exception:
            pass

        return self._portfolio_template(context)

    def _template_fallback(self, ctx: dict[str, Any]) -> str:
        """Template deterministico per narrativa mercato."""
        regime = ctx.get("regime", "unknown")
        vix = ctx.get("vix")
        score = ctx.get("composite_score")
        news = ctx.get("news_score")

        parts: list[str] = []

        if regime == "bull":
            parts.append("Il mercato mostra un regime rialzista.")
        elif regime == "bear":
            parts.append("Il mercato è in fase ribassista.")
        elif regime == "transition":
            parts.append("Il mercato è in una fase di transizione.")
        else:
            parts.append("Il regime di mercato è attualmente incerto.")

        if vix is not None:
            if float(vix) > 30:
                parts.append(f"La volatilità implicita è elevata (VIX: {vix:.1f}).")
            elif float(vix) < 15:
                parts.append(f"La volatilità è contenuta (VIX: {vix:.1f}).")
            else:
                parts.append(f"La volatilità si mantiene in range normale (VIX: {vix:.1f}).")

        if score is not None:
            s = float(score)
            if s > 0.3:
                parts.append(f"Il segnale composito è positivo ({s:+.2f}).")
            elif s < -0.3:
                parts.append(f"Il segnale composito è negativo ({s:+.2f}).")

        if news is not None:
            n = float(news)
            if abs(n) > 0.2:
                sentiment = "favorevole" if n > 0 else "sfavorevole"
                parts.append(f"Il flusso di notizie è {sentiment} ({n:+.2f}).")

        parts.append("Fonte: Template strutturato · LLM: DISABLED")
        return " ".join(parts)

    def _portfolio_template(self, ctx: dict[str, Any]) -> str:
        """Template deterministico per commento portafoglio."""
        value = ctx.get("total_value")
        pnl = ctx.get("pnl_pct")
        parts: list[str] = ["Riepilogo portafoglio:"]
        if value is not None:
            parts.append(f"Valore totale {value:,.0f} USD.")
        if pnl is not None:
            p = float(pnl)
            parts.append(f"Performance: {p:+.2f}%.")
        parts.append("Fonte: Template strutturato · LLM: DISABLED")
        return " ".join(parts)
