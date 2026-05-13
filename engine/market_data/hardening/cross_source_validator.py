"""CrossSourceValidator — confronto multi-sorgente per rilevare discrepanze.

Confronta la stessa metrica (prezzo, P/E, market_cap, ecc.) proveniente
da due sorgenti diverse e segnala discrepanze che superano le soglie
configurate in ``config/cross_source_config.yaml``.

Pattern d'uso tipico:
    validator = CrossSourceValidator()
    results = validator.validate_price(
        ticker="AAPL",
        value_a=150.0, source_a="yfinance",
        value_b=151.5, source_b="finnhub",
    )
    # results.is_valid == True se discrepanza < 0.5%

Output: lista di ``ValidationResult`` per ogni metrica confrontata.
Se una discrepanza supera la soglia:
  · Il risultato è WARN (non blocca il calcolo — solo segnalazione).
  · Viene scritto un alert in ``data_quality_alerts`` (migration 012).

Regola 8: tutti i calcoli percentuali usano numpy.float64.
Regola 7: soglie lette da cross_source_config.yaml, mai hardcoded.

ANTI-REGRESSIONE (v9.0 Sett.2):
  · Il validator non modifica i dati — solo reporting.
  · Gestisce gracefully il caso in cui una delle due sorgenti è NaN
    (fonte offline / dati non disponibili) → skip senza alert.
  · Il cross_source_config.yaml ha già i campi necessari come stub
    (creato in v8.0) — questo modulo lo porta in produzione.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from shared.db.duckdb_client import DuckDBClient, get_duckdb_client
from shared.exceptions import DatabaseError
from shared.logger import get_logger

__version__ = "9.0.0"
__all__ = ["CrossSourceValidator", "ValidationResult"]

log = get_logger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "cross_source_config.yaml"

# Fallback defaults se la config non è disponibile (Regola 7: nominati)
_DEFAULT_THRESHOLDS: dict[str, dict[str, float]] = {
    "price":          {"max_pct_diff": 0.005, "quality_penalty_factor": 2.0},
    "pe_ratio":       {"max_pct_diff": 0.10,  "quality_penalty_factor": 1.5},
    "market_cap":     {"max_pct_diff": 0.05,  "quality_penalty_factor": 1.5},
    "eps_ttm":        {"max_pct_diff": 0.08,  "quality_penalty_factor": 1.5},
    "dividend_yield": {"max_pct_diff": 0.10,  "quality_penalty_factor": 1.0},
    "revenue_ttm":    {"max_pct_diff": 0.05,  "quality_penalty_factor": 1.0},
}


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Risultato di un singolo confronto cross-source."""

    ticker: str
    metric_name: str
    value_a: float
    source_a: str
    value_b: float
    source_b: str
    pct_diff: float    # |a - b| / max(|a|, |b|)  — sempre >= 0
    threshold: float   # soglia della config
    is_valid: bool     # True se pct_diff < threshold


@dataclass
class ValidationReport:
    """Aggregato di tutti i ValidationResult per un ticker."""

    ticker: str
    results: list[ValidationResult] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return any(not r.is_valid for r in self.results)

    @property
    def violations(self) -> list[ValidationResult]:
        return [r for r in self.results if not r.is_valid]


class CrossSourceValidator:
    """Confronta metriche da sorgenti diverse per un ticker.

    Persiste le violazioni nella tabella ``data_quality_alerts``
    con ``alert_kind='cross_source_discrepancy'``.
    """

    def __init__(self, client: DuckDBClient | None = None) -> None:
        self._client = client or get_duckdb_client()
        self._thresholds = self._load_thresholds()

    # ─── Public API ────────────────────────────────────────────────────────

    def validate_price(
        self,
        ticker: str,
        value_a: float,
        source_a: str,
        value_b: float,
        source_b: str,
    ) -> ValidationResult:
        """Confronta il prezzo da due sorgenti."""
        return self._compare(
            ticker=ticker,
            metric_name="price",
            value_a=value_a,
            source_a=source_a,
            value_b=value_b,
            source_b=source_b,
        )

    def validate_pe_ratio(
        self,
        ticker: str,
        value_a: float,
        source_a: str,
        value_b: float,
        source_b: str,
    ) -> ValidationResult:
        """Confronta P/E TTM da due sorgenti."""
        return self._compare(
            ticker=ticker,
            metric_name="pe_ratio",
            value_a=value_a,
            source_a=source_a,
            value_b=value_b,
            source_b=source_b,
        )

    def validate_market_cap(
        self,
        ticker: str,
        value_a: float,
        source_a: str,
        value_b: float,
        source_b: str,
    ) -> ValidationResult:
        """Confronta market cap da due sorgenti."""
        return self._compare(
            ticker=ticker,
            metric_name="market_cap",
            value_a=value_a,
            source_a=source_a,
            value_b=value_b,
            source_b=source_b,
        )

    def validate_batch(
        self,
        ticker: str,
        metrics: dict[str, tuple[float, str, float, str]],
    ) -> ValidationReport:
        """Confronta un batch di metriche per lo stesso ticker.

        Args:
            ticker: Ticker equity.
            metrics: {metric_name: (value_a, source_a, value_b, source_b)}.

        Returns:
            ValidationReport con tutti i risultati.

        Esempio::
            report = validator.validate_batch("AAPL", {
                "price": (150.0, "yfinance", 151.5, "finnhub"),
                "pe_ratio": (28.5, "alpha_vantage", 29.0, "finnhub"),
            })
        """
        report = ValidationReport(ticker=ticker)
        for metric_name, (va, sa, vb, sb) in metrics.items():
            result = self._compare(
                ticker=ticker,
                metric_name=metric_name,
                value_a=va,
                source_a=sa,
                value_b=vb,
                source_b=sb,
            )
            report.results.append(result)

        # Persiste le violazioni
        for violation in report.violations:
            self._persist_discrepancy(violation)

        if report.has_violations:
            log.warning(
                "cross_source.violations_found",
                ticker=ticker,
                count=len(report.violations),
                metrics=[v.metric_name for v in report.violations],
            )
        return report

    # ─── Core comparison ───────────────────────────────────────────────────

    def _compare(
        self,
        *,
        ticker: str,
        metric_name: str,
        value_a: float,
        source_a: str,
        value_b: float,
        source_b: str,
    ) -> ValidationResult:
        """Calcola la discrepanza percentuale e la confronta con la soglia.

        pct_diff = |a - b| / max(|a|, |b|)

        Casi speciali:
          · Se entrambi NaN → is_valid=True (skip silenzioso)
          · Se uno solo è NaN → is_valid=True (fonte non disponibile, skip)
          · Se entrambi zero → pct_diff=0.0, is_valid=True
        """
        threshold = self._thresholds.get(metric_name, {}).get(
            "max_pct_diff", 0.05
        )

        # Skip graceful: uno o entrambi i valori mancanti
        if math.isnan(value_a) or math.isnan(value_b):
            return ValidationResult(
                ticker=ticker,
                metric_name=metric_name,
                value_a=value_a,
                source_a=source_a,
                value_b=value_b,
                source_b=source_b,
                pct_diff=float(np.nan),
                threshold=threshold,
                is_valid=True,  # non possiamo confrontare → skip
            )

        # Calcolo numpy float64 (Regola 8)
        a = np.float64(value_a)
        b = np.float64(value_b)
        denominator = max(abs(a), abs(b))

        if denominator == 0.0:
            pct_diff = 0.0
        else:
            pct_diff = float(abs(a - b) / denominator)

        is_valid = pct_diff < threshold

        if not is_valid:
            log.info(
                "cross_source.discrepancy",
                ticker=ticker,
                metric=metric_name,
                source_a=source_a,
                value_a=round(float(a), 4),
                source_b=source_b,
                value_b=round(float(b), 4),
                pct_diff=round(pct_diff * 100, 2),
                threshold_pct=round(threshold * 100, 2),
            )

        return ValidationResult(
            ticker=ticker,
            metric_name=metric_name,
            value_a=float(a),
            source_a=source_a,
            value_b=float(b),
            source_b=source_b,
            pct_diff=pct_diff,
            threshold=threshold,
            is_valid=is_valid,
        )

    # ─── Persistence ───────────────────────────────────────────────────────

    def _persist_discrepancy(self, result: ValidationResult) -> None:
        """Scrive una discrepanza nella tabella data_quality_alerts."""
        detail = (
            f"{result.metric_name}: {result.source_a}={result.value_a:.4f} vs "
            f"{result.source_b}={result.value_b:.4f} "
            f"(diff {result.pct_diff * 100:.2f}% > soglia {result.threshold * 100:.1f}%)"
        )
        try:
            with self._client.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO data_quality_alerts
                    (series_id, alert_kind, severity, threshold,
                     detail, source_a, source_b, metric_name, pct_diff, created_at)
                    VALUES (?, 'cross_source_discrepancy', 'WARNING', ?, ?, ?, ?, ?, ?, NOW())
                    """,
                    [
                        result.ticker,
                        float(result.threshold),
                        detail[:500],
                        result.source_a,
                        result.source_b,
                        result.metric_name,
                        float(result.pct_diff),
                    ],
                )
        except Exception as exc:
            # Non propagare: un errore di persistenza non deve
            # bloccare il flusso di analisi principale.
            log.warning(
                "cross_source.persist_failed",
                ticker=result.ticker,
                error=str(exc)[:100],
            )

    # ─── Config ────────────────────────────────────────────────────────────

    @staticmethod
    def _load_thresholds() -> dict[str, dict[str, float]]:
        """Carica le soglie da cross_source_config.yaml.

        Fallback ai default nominati se il file non esiste o è malformato.
        """
        try:
            with _CONFIG_PATH.open() as f:
                raw: dict[str, Any] = yaml.safe_load(f) or {}
            # Filtra solo le chiavi metriche con max_pct_diff
            result: dict[str, dict[str, float]] = {}
            for key, val in raw.items():
                if isinstance(val, dict) and "max_pct_diff" in val:
                    result[key] = {
                        "max_pct_diff": float(val["max_pct_diff"]),
                        "quality_penalty_factor": float(
                            val.get("quality_penalty_factor", 1.0)
                        ),
                    }
            if not result:
                raise ValueError("Config vuota o nessuna metrica trovata")
            return result
        except Exception as exc:
            log.warning(
                "cross_source.config_load_error",
                error=str(exc)[:100],
                fallback="using defaults",
            )
            return _DEFAULT_THRESHOLDS
