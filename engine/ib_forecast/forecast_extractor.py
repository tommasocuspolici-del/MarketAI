"""Forecast Extractor — Two-stage: regex (Stage 1) + LLM (Stage 2).

Stage 1 (questa fase): regex pattern su testi IB strutturati.
Stage 2 (Fase 9): LLM parsing semantico via LLMGateway (stub implementato qui).

Regola 33: zero previsioni simulate.
Regola 34: forecast cachati in ib_forecasts.
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from engine.ib_forecast.schemas import ExtractedForecast
from shared.feature_flags import is_enabled
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient
    from shared.llm.llm_gateway import LLMGateway

__version__ = "1.0.0"
__all__ = ["ForecastExtractor"]

log = get_logger(__name__)

# ─── Pattern regex per indicatori economici ───────────────────────────────────
_PATTERNS: dict[str, list[str]] = {
    "GDP": [
        r"GDP\s+(?:growth|forecast|outlook)\s+(?:of\s+|expected\s+to\s+reach\s+|to\s+reach\s+)?([+-]?\d+\.?\d*)\s*%",
        r"GDP\s+(?:growth|forecast|outlook)\s+\w+\s+\w+\s+(?:reach\s+)?([+-]?\d+\.?\d*)\s*%",
        r"economic\s+growth\s+(?:of\s+|expected\s+to\s+reach\s+)?([+-]?\d+\.?\d*)\s*(?:percent|%)",
        r"real\s+GDP\s+(?:to\s+)?(?:grow|expand|contract|reach)\s+(?:by\s+)?([+-]?\d+\.?\d*)\s*%",
        r"GDP\s+(?:to\s+(?:reach|grow|expand)\s+)?([+-]?\d+\.?\d*)\s*%",
        r"growth\s+(?:of\s+|at\s+|to\s+)?([+-]?\d+\.?\d*)\s*%\s+(?:in\s+20\d{2}|for\s+20\d{2})",
    ],
    "CPI": [
        r"CPI\s+(?:inflation\s+)?(?:of\s+)?([+-]?\d+\.?\d*)\s*%",
        r"inflation\s+(?:rate\s+)?(?:of\s+|at\s+|expected\s+(?:at|for)\s+)?([+-]?\d+\.?\d*)\s*%",
        r"price\s+(?:growth|inflation)\s+(?:of\s+)?([+-]?\d+\.?\d*)\s*%",
        r"headline\s+inflation\s+(?:to\s+|at\s+|of\s+)?([+-]?\d+\.?\d*)\s*%",
    ],
    "FEDFUNDS": [
        r"federal\s+funds\s+rate\s+(?:of\s+|at\s+|to\s+(?:reach\s+)?)?([+-]?\d+\.?\d*)\s*%",
        r"(?:interest\s+)?rate\s+(?:hike|cut|increase|decrease)\s+(?:to\s+)?([+-]?\d+\.?\d*)\s*%",
        r"policy\s+rate\s+(?:at\s+|to\s+)?([+-]?\d+\.?\d*)\s*%",
        r"fed\s+rate\s+(?:at\s+|to\s+)?([+-]?\d+\.?\d*)\s*%",
    ],
    "SP500": [
        r"S&P\s*500\s+(?:target|forecast|outlook)\s+(?:of\s+)?(\d{4,5})",
        r"S&P\s+(?:to\s+reach|target)\s+(\d{4,5})",
        r"index\s+target\s+(?:of\s+)?(\d{4,5})",
    ],
    "UNEMPLOYMENT": [
        r"unemployment\s+(?:rate\s+)?(?:of\s+|at\s+|to\s+)?([+-]?\d+\.?\d*)\s*%",
        r"jobless\s+rate\s+(?:at\s+|of\s+)?([+-]?\d+\.?\d*)\s*%",
    ],
}

# Pattern per estrarre anno/horizon dal testo
_HORIZON_PATTERNS = [
    (r"\b(20\d{2})\b", "{}"),
    (r"\b(Q[1-4])\s+(20\d{2})\b", "{}_{}"),
    (r"\b(H[12])\s+(20\d{2})\b", "{}_{}"),
    (r"\bnext\s+(\d{2})\s+months?\b", "{}M"),
    (r"\b(12)\s+months?\b", "12M"),
]


class ForecastExtractor:
    """Estrae previsioni da testo free-form tramite regex (Stage 1) o LLM (Stage 2).

    Args:
        client:      DuckDBClient per persistenza.
        llm_gateway: LLMGateway (inattivo finché ib_llm_extraction=false).

    Usage::

        extractor = ForecastExtractor(client=get_duckdb_client())
        forecast = extractor.extract("GDP expected to grow 2.5% in 2025", "fed_speeches")
    """

    def __init__(
        self,
        client: DuckDBClient,
        llm_gateway: "LLMGateway | None" = None,
    ) -> None:
        self._client = client
        self._llm = llm_gateway

    def extract(self, text: str, source: str, report_id: str | None = None) -> list[ExtractedForecast]:
        """Estrae previsioni da testo.

        Stage 2: LLM attivato se is_enabled("ib_llm_extraction") e llm disponibile.
        Stage 1: regex — sempre disponibile, fallback trasparente.
        """
        if not text or not source:
            return []

        report_id = report_id or str(uuid.uuid4())[:16]

        # Stage 2: LLM (inattivo di default — Fase 9 lo attiva)
        if (is_enabled("ib_llm_extraction") and self._llm is not None
                and self._llm.is_available()):
            try:
                return self._extract_llm(text, source, report_id)
            except Exception as exc:
                log.warning("forecast_extractor.llm_failed", source=source, error=str(exc)[:100])

        # Stage 1: regex (sempre disponibile)
        return self._extract_regex(text, source, report_id)

    def _extract_regex(self, text: str, source: str, report_id: str) -> list[ExtractedForecast]:
        """Stage 1: regex pattern matching su indicatori chiave."""
        forecasts: list[ExtractedForecast] = []
        text_lower = text.lower()
        now = datetime.now(UTC)

        for indicator, patterns in _PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, text_lower, re.IGNORECASE):
                    try:
                        value_str = match.group(1).replace(",", "")
                        value = float(value_str)

                        # Cerca horizon nel contesto intorno al match
                        start = max(0, match.start() - 100)
                        end = min(len(text), match.end() + 100)
                        context = text[start:end]
                        horizon = self._extract_horizon(context)

                        forecasts.append(ExtractedForecast(
                            report_id=report_id,
                            source=source,
                            indicator=indicator,
                            horizon=horizon,
                            value=value,
                            extraction_method="regex",
                            confidence=0.7,
                            fetched_at=now,
                        ))
                        break  # Un match per pattern per indicatore
                    except (ValueError, IndexError):
                        continue

        if forecasts:
            self._persist(forecasts)
        return forecasts

    def _extract_llm(self, text: str, source: str, report_id: str) -> list[ExtractedForecast]:
        """Stage 2: LLM parsing semantico.

        Implementato come stub in Fase 8.
        Diventa funzionale quando llm_engine_enabled = true (Fase 9).
        """
        assert self._llm is not None
        result = self._llm.generate(
            template="ib_extraction",
            context={"text": text[:800], "source": source},
            max_tokens=256,
        )
        return self._parse_llm_json(result.text, source, report_id)

    def _parse_llm_json(self, json_text: str, source: str, report_id: str) -> list[ExtractedForecast]:
        """Parsa output JSON dall'LLM in ExtractedForecast."""
        import json
        now = datetime.now(UTC)
        try:
            data = json.loads(json_text)
            forecasts = []
            for item in data if isinstance(data, list) else [data]:
                forecasts.append(ExtractedForecast(
                    report_id=report_id,
                    source=source,
                    indicator=item.get("indicator", "UNKNOWN"),
                    horizon=item.get("horizon", "2025"),
                    value=float(item.get("value")) if item.get("value") is not None else None,
                    extraction_method="llm",
                    confidence=float(item.get("confidence", 0.85)),
                    fetched_at=now,
                ))
            return forecasts
        except Exception as exc:
            log.warning("forecast_extractor.llm_parse_failed", error=str(exc)[:100])
            return []

    def _extract_horizon(self, context: str) -> str:
        """Estrae l'orizzonte temporale dal contesto."""
        for pattern, fmt in _HORIZON_PATTERNS:
            match = re.search(pattern, context, re.IGNORECASE)
            if match:
                groups = match.groups()
                if len(groups) == 1:
                    return fmt.format(groups[0])
                elif len(groups) == 2:
                    return fmt.format(groups[0], groups[1])
        return "2025"

    def _persist(self, forecasts: list[ExtractedForecast]) -> None:
        """Salva previsioni in ib_forecasts (Regola 34)."""
        for f in forecasts:
            try:
                self._client.execute(
                    """
                    INSERT INTO ib_forecasts
                        (report_id, source, indicator, horizon, value,
                         value_range_low, value_range_high, unit,
                         extraction_method, confidence, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [f.report_id, f.source, f.indicator, f.horizon, f.value,
                     f.value_range_low, f.value_range_high, f.unit,
                     f.extraction_method, f.confidence, f.fetched_at],
                )
            except Exception as exc:
                log.debug("forecast_extractor.persist_skip", error=str(exc)[:80])
