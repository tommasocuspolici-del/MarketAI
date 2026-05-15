"""CorrelationSignalGenerator — segnale correlazioni per Composite Signal v2.

Legge da cross_asset_regime (CrossAssetMatrix) e lead_lag_signals
(LeadLagAnalyzer) per produrre il segnale correlazioni finale.

Segnale composito:
  85% → correlation_signal da cross_asset_regime (diversification + credit-equity)
  15% → lead_lag_signal aggregato da lead_lag_signals (net bullish/bearish)

Valori positivi = ambiente sano (asset decorrelati, risk-on ordinato).
Valori negativi = stress (asset correlati, fuga verso qualità).

Regola 12: legge da DuckDB — nessun fetch inline.
Regola 29: gated da feature flag 'correlation_signal_composite'.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

import numpy as np

from shared.feature_flags import is_enabled
from shared.exceptions import FeatureDisabledError

if TYPE_CHECKING:
    import pandas as pd
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["CorrelationSignalGenerator", "CorrelationSignalResult"]

log = logging.getLogger(__name__)

# Pesi aggregazione segnale
_W_CORR     = 0.85   # peso correlation_signal da cross_asset_regime
_W_LEAD_LAG = 0.15   # peso segnale lead-lag aggregato

# Staleness: segnale ignorato se più vecchio di N giorni
_MAX_STALENESS_DAYS = 7


@dataclass(frozen=True)
class CorrelationSignalResult:
    """Output del CorrelationSignalGenerator.

    Attributes:
        signal_date:           Data del segnale.
        correlation_signal:    Segnale composito finale [-1, +1].
        cross_asset_component: Contributo cross_asset_regime [-1, +1].
        lead_lag_component:    Contributo lead-lag [-1, +1] (None se N/D).
        diversification_score: Score diversificazione [0, 1].
        vix_regime:            Regime VIX ('normal'|'crisis_coupling'|'divergence').
        avg_equity_bond_corr:  Correlazione equity-bond (proxy regime).
        lead_lag_count:        Relazioni Granger significative disponibili.
        data_freshness_days:   Giorni dall'ultimo aggiornamento cross_asset_regime.
        confidence:            Confidenza [0, 1] basata su freshness e dati.
    """
    signal_date:           date
    correlation_signal:    float
    cross_asset_component: float
    lead_lag_component:    float | None
    diversification_score: float | None
    vix_regime:            str | None
    avg_equity_bond_corr:  float | None
    lead_lag_count:        int
    data_freshness_days:   int
    confidence:            float


class CorrelationSignalGenerator:
    """Genera il segnale correlazioni per Composite Signal v2.

    Combina:
      · cross_asset_regime → diversification + credit/equity dynamics
      · lead_lag_signals   → relazioni Granger significative (nette)

    Usage::

        gen = CorrelationSignalGenerator(client=get_duckdb_client())
        result = gen.compute_from_db()
        print(result.correlation_signal, result.confidence)

        # Per integrare nel Composite Signal:
        signal = gen.get_latest_signal()
    """

    def __init__(self, client: DuckDBClient) -> None:
        if not is_enabled("correlation_signal_composite"):
            raise FeatureDisabledError(
                "Feature 'correlation_signal_composite' is disabled. "
                "Abilita in config/feature_flags.yaml."
            )
        self._client = client

    # ─── Public API ──────────────────────────────────────────────────────────

    def get_latest_signal(self) -> float | None:
        """Legge il segnale più recente da cross_asset_regime.

        Interfaccia per CompositeSignalAggregator.

        Returns:
            Signal [-1, +1] o None se non disponibile o dati stale.
        """
        try:
            rows = self._client.query(
                "SELECT correlation_signal, regime_date FROM cross_asset_regime "
                "ORDER BY regime_date DESC LIMIT 1"
            )
            if not rows or rows[0][0] is None:
                return None
            raw_signal = float(rows[0][0])
            # Verifica freshness
            regime_date = rows[0][1]
            if isinstance(regime_date, str):
                from datetime import datetime
                regime_date = datetime.fromisoformat(regime_date).date()
            staleness = (date.today() - regime_date).days
            if staleness > _MAX_STALENESS_DAYS:
                log.debug("correlation_signal.stale days=%d", staleness)
                return None
            return float(np.clip(raw_signal, -1.0, 1.0))
        except Exception as exc:
            log.debug("correlation_signal.read_failed: %s", str(exc)[:80])
            return None

    def compute_from_db(self, as_of: date | None = None) -> CorrelationSignalResult:
        """Calcola il segnale composito da dati già in DuckDB.

        Legge cross_asset_regime e lead_lag_signals, aggrega.

        Args:
            as_of: Data di riferimento (default: oggi).

        Returns:
            CorrelationSignalResult con segnale e contesto.
        """
        as_of = as_of or date.today()

        cross_row  = self._read_cross_asset(as_of)
        lead_lag   = self._read_lead_lag_signal(as_of)
        freshness  = self._compute_freshness(cross_row, as_of)
        confidence = self._compute_confidence(cross_row, freshness, lead_lag[1])

        cross_signal = cross_row.get("correlation_signal", 0.0) or 0.0
        ll_signal    = lead_lag[0]

        if ll_signal is not None:
            combined = float(np.clip(
                _W_CORR * cross_signal + _W_LEAD_LAG * ll_signal,
                -1.0, 1.0,
            ))
        else:
            combined = float(np.clip(cross_signal, -1.0, 1.0))

        return CorrelationSignalResult(
            signal_date=as_of,
            correlation_signal=combined,
            cross_asset_component=float(cross_signal),
            lead_lag_component=ll_signal,
            diversification_score=cross_row.get("diversification_score"),
            vix_regime=cross_row.get("vix_correlation_regime"),
            avg_equity_bond_corr=cross_row.get("avg_equity_bond_corr"),
            lead_lag_count=lead_lag[1],
            data_freshness_days=freshness,
            confidence=confidence,
        )

    def run_full_pipeline(
        self,
        returns: "pd.DataFrame",
        regime_labels: "pd.Series | None" = None,
        as_of: date | None = None,
    ) -> CorrelationSignalResult:
        """Esegue CrossAssetMatrix su dati freschi e restituisce il segnale.

        Questo metodo fa CALCOLO + PERSIST (non solo lettura).
        Usato dal job scheduler settimanale.

        Args:
            returns:       DataFrame rendimenti log (col=asset, row=date).
            regime_labels: Etichette regime per ogni data.
            as_of:         Data snapshot (default: oggi).

        Returns:
            CorrelationSignalResult aggiornato.
        """
        from engine.analytics.correlation.cross_asset_matrix import CrossAssetMatrix

        as_of = as_of or date.today()
        matrix = CrossAssetMatrix(client=self._client)
        matrix_result = matrix.compute(returns, regime_labels, snapshot_date=as_of)

        # Dopo il compute+persist, leggi da DB per ottenere il segnale aggiornato
        return self.compute_from_db(as_of)

    # ─── Internal helpers ────────────────────────────────────────────────────

    def _read_cross_asset(self, as_of: date) -> dict:
        """Legge riga più recente da cross_asset_regime."""
        try:
            rows = self._client.query(
                """
                SELECT correlation_signal, diversification_score,
                       vix_correlation_regime, avg_equity_bond_corr,
                       avg_equity_gold_corr, credit_equity_corr,
                       regime_date
                FROM cross_asset_regime
                WHERE regime_date <= ?
                ORDER BY regime_date DESC LIMIT 1
                """,
                [as_of],
            )
            if rows:
                return {
                    "correlation_signal":    rows[0][0],
                    "diversification_score": rows[0][1],
                    "vix_correlation_regime":rows[0][2],
                    "avg_equity_bond_corr":  rows[0][3],
                    "avg_equity_gold_corr":  rows[0][4],
                    "credit_equity_corr":    rows[0][5],
                    "regime_date":           rows[0][6],
                }
        except Exception as exc:
            log.debug("correlation_signal.cross_asset_read_failed: %s", str(exc)[:80])
        return {}

    def _read_lead_lag_signal(self, as_of: date) -> tuple[float | None, int]:
        """Aggrega i segnali Granger significativi.

        Returns:
            (net_signal, n_significant):
              net_signal: media pesata dei segnali bullish/bearish significativi.
              n_significant: numero di relazioni significative.
        """
        try:
            cutoff = as_of - timedelta(days=30)
            rows = self._client.query(
                """
                SELECT lead_signal, cross_corr_peak, granger_pvalue
                FROM lead_lag_signals
                WHERE analysis_date BETWEEN ? AND ?
                  AND is_significant = TRUE
                ORDER BY analysis_date DESC, granger_pvalue ASC
                """,
                [cutoff, as_of],
            )
            if not rows:
                return None, 0

            # Converti lead_signal in valore numerico pesato per cross_corr
            signal_vals: list[float] = []
            for row in rows:
                lead   = str(row[0]) if row[0] else "neutral"
                corr   = abs(float(row[1])) if row[1] is not None else 0.3
                pvalue = float(row[2]) if row[2] is not None else 0.05

                if lead == "bullish_lead":
                    signal_vals.append(+corr * (1.0 - pvalue))
                elif lead == "bearish_lead":
                    signal_vals.append(-corr * (1.0 - pvalue))
                # neutral → skip (non contribuisce)

            if not signal_vals:
                return None, len(rows)

            net = float(np.clip(np.mean(signal_vals), -1.0, 1.0))
            return net, len(rows)

        except Exception as exc:
            log.debug("correlation_signal.lead_lag_read_failed: %s", str(exc)[:80])
            return None, 0

    @staticmethod
    def _compute_freshness(cross_row: dict, as_of: date) -> int:
        """Giorni dall'ultimo aggiornamento cross_asset_regime."""
        regime_date = cross_row.get("regime_date")
        if regime_date is None:
            return 999
        if isinstance(regime_date, str):
            from datetime import datetime
            regime_date = datetime.fromisoformat(regime_date).date()
        try:
            return max(0, (as_of - regime_date).days)
        except Exception:
            return 999

    @staticmethod
    def _compute_confidence(
        cross_row: dict,
        freshness_days: int,
        n_lead_lag: int,
    ) -> float:
        """Confidenza [0, 1] basata su: freshness dati + lead-lag disponibili."""
        if not cross_row:
            return 0.0

        # Decadimento esponenziale sulla freshness
        freshness_score = float(np.exp(-freshness_days / 5.0))  # dimezza ogni 5gg

        # Bonus lead-lag (max +20% quando >= 5 relazioni significative)
        ll_bonus = float(np.clip(n_lead_lag / 5.0, 0.0, 0.2))

        raw = freshness_score * 0.8 + ll_bonus
        return float(np.clip(raw, 0.0, 1.0))
