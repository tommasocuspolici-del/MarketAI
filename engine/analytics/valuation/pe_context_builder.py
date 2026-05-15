"""Contestualizzazione storica delle metriche PE (z-score, percentile).

Standard investment bank: ogni metrica è sempre presentata in contesto
storico (z-score 20 anni, percentile, regime).

Regola 8: numpy per calcoli statistici.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING

import numpy as np
from scipy import stats

from engine.analytics.valuation.schemas import PEMetrics, ValuationLabel

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
log = logging.getLogger(__name__)

# Medie storiche approssimate S&P 500 (1990-2025) per fallback senza storico DB
_HISTORICAL_FALLBACK = {
    "trailing_pe_mean": 17.5,
    "trailing_pe_std":   5.0,
    "forward_pe_mean":  15.5,
    "forward_pe_std":    4.0,
    "cape_mean":        23.0,
    "cape_std":          8.0,
}

# Soglie label valuation (su z-score composito)
_DEEP_VALUE_THRESHOLD    = -1.5
_CHEAP_THRESHOLD         = -0.5
_FAIR_VALUE_MIN          = -0.5
_FAIR_VALUE_MAX          =  0.5
_STRETCHED_THRESHOLD     =  0.5
_BUBBLE_WARNING_THRESHOLD = 1.5


class PEContextBuilder:
    """Calcola z-score, percentile e label per le metriche PE.

    Usa la serie storica in pe_metrics (o shiller_cape_historical per CAPE)
    per contestualizzare i valori correnti.

    Usage::

        builder = PEContextBuilder(client=get_duckdb_client())
        z_trailing, z_forward, z_cape, pct_t, pct_f, pct_c, label = builder.build(metrics)
    """

    def __init__(self, client: DuckDBClient, lookback_years: int = 20) -> None:
        self._client = client
        self._lookback = lookback_years

    def build(self, metrics: PEMetrics) -> dict:
        """Calcola contesto storico per le metriche PE.

        Args:
            metrics: PEMetrics calcolate per oggi.

        Returns:
            Dict con: trailing_zscore, forward_zscore, cape_zscore,
            trailing_pct, forward_pct, cape_pct, label, composite_score.
        """
        cutoff = metrics.metric_date - timedelta(days=self._lookback * 365)

        # Serie storiche da DB
        hist_trailing = self._get_hist_series("trailing_pe", metrics.ticker, cutoff)
        hist_forward  = self._get_hist_series("forward_pe",  metrics.ticker, cutoff)
        hist_cape     = self._get_hist_cape(cutoff)

        # Z-score e percentile per ogni metrica
        z_t, p_t = self._compute_zp(metrics.trailing_pe, hist_trailing,
                                     _HISTORICAL_FALLBACK["trailing_pe_mean"],
                                     _HISTORICAL_FALLBACK["trailing_pe_std"])
        z_f, p_f = self._compute_zp(metrics.forward_pe, hist_forward,
                                     _HISTORICAL_FALLBACK["forward_pe_mean"],
                                     _HISTORICAL_FALLBACK["forward_pe_std"])
        z_c, p_c = self._compute_zp(metrics.shiller_cape, hist_cape,
                                     _HISTORICAL_FALLBACK["cape_mean"],
                                     _HISTORICAL_FALLBACK["cape_std"])

        # ERP z-score (invertito: ERP alto = positivo = sottovalutato)
        erp_contribution = 0.0
        if metrics.erp_implied is not None:
            # ERP > 3% → z_erp positivo (buono per azioni)
            erp_contribution = float(np.clip((metrics.erp_implied - 0.02) / 0.015, -2, 2))

        # Score composito valuation (pesi roadmap)
        # Nota: z-score positivo = metrica ALTA = costosa → segnale negativo per investitore
        composite_z = float(
            0.30 * (z_t or 0.0) +
            0.35 * (z_f or 0.0) +
            0.20 * (z_c or 0.0) +
            0.15 * (-erp_contribution)  # ERP alto (buono) → score positivo
        )
        # composite_z > 0 = costoso, < 0 = economico
        # Invertiamo per avere: +1 = deep value, -1 = bubble
        composite_score = float(np.clip(-composite_z / 2.0, -1.0, 1.0))

        label = self._assign_label(composite_z)

        return {
            "trailing_zscore":  z_t,
            "forward_zscore":   z_f,
            "cape_zscore":      z_c,
            "trailing_pct":     p_t,
            "forward_pct":      p_f,
            "cape_pct":         p_c,
            "composite_score":  composite_score,
            "label":            label,
        }

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _get_hist_series(self, col: str, ticker: str, cutoff: date) -> np.ndarray:
        try:
            rows = self._client.query(
                f"SELECT {col} FROM pe_metrics "
                f"WHERE ticker=? AND metric_date>=? AND {col} IS NOT NULL "
                f"ORDER BY metric_date",
                [ticker, cutoff],
            )
            return np.array([float(r[0]) for r in rows], dtype=float)
        except Exception:
            return np.array([], dtype=float)

    def _get_hist_cape(self, cutoff: date) -> np.ndarray:
        try:
            rows = self._client.query(
                "SELECT cape_ratio FROM shiller_cape_historical "
                "WHERE data_date>=? AND cape_ratio IS NOT NULL ORDER BY data_date",
                [cutoff],
            )
            return np.array([float(r[0]) for r in rows], dtype=float)
        except Exception:
            return np.array([], dtype=float)

    @staticmethod
    def _compute_zp(
        value: float | None,
        history: np.ndarray,
        fallback_mean: float,
        fallback_std: float,
    ) -> tuple[float | None, float | None]:
        """Calcola z-score e percentile con fallback ai valori storici."""
        if value is None:
            return None, None
        if len(history) >= 12:
            mean = float(np.mean(history))
            std  = float(np.std(history, ddof=1))
            if std < 0.01:
                std = fallback_std
            z = (value - mean) / std
            p = float(stats.percentileofscore(history, value))
        else:
            z = (value - fallback_mean) / fallback_std
            p = float(stats.norm.cdf(z) * 100)
        return float(np.clip(z, -5, 5)), float(np.clip(p, 0, 100))

    @staticmethod
    def _assign_label(composite_z: float) -> ValuationLabel:
        """Assegna label qualitativo in base al z-score composito."""
        if composite_z <= _DEEP_VALUE_THRESHOLD:
            return "deep_value"
        if composite_z <= _CHEAP_THRESHOLD:
            return "cheap"
        if composite_z <= _STRETCHED_THRESHOLD:
            return "fair_value"
        if composite_z <= _BUBBLE_WARNING_THRESHOLD:
            return "stretched"
        return "bubble_warning"
