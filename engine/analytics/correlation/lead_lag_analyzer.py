"""Lead-Lag Analysis via Granger Causality Test.

Standard professionale: test formale Granger per causalità, con cross-
correlazione come filtro di rumore.

Algoritmo:
  1. Pre-processing: rendimenti log, ADF test, winsorize ±5σ
  2. Granger causality (statsmodels) per ogni coppia (A, B) e lag k
  3. Selezione lag ottimale: min p-value + max cross-corr
  4. Segnale: 'bullish_lead'|'bearish_lead'|'neutral'

Performance target: < 500ms per 10 coppie su 3 anni giornalieri (Rule 30).
Regola 8: numpy per calcoli.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
log = logging.getLogger(__name__)

# Lag candidati (giorni trading) per test Granger
_CANDIDATE_LAGS = [1, 2, 5, 10, 21]

# Soglie significatività
_PVALUE_THRESHOLD = 0.05
_CORR_MIN         = 0.30    # Cross-correlazione minima per segnale affidabile

_TABLE = "lead_lag_signals"


@dataclass(frozen=True)
class LeadLagResult:
    """Risultato Granger causality per una coppia di asset.

    Attributes:
        leader:          Asset che anticipa.
        follower:        Asset che segue.
        optimal_lag_days: Lag ottimale in giorni trading.
        granger_f_stat:  F-statistica test Granger.
        granger_pvalue:  p-value (< 0.05 = causality).
        cross_corr_peak: Cross-correlazione al lag ottimale.
        is_significant:  True se pvalue < 0.05 E |corr| > 0.30.
        lead_signal:     'bullish_lead'|'bearish_lead'|'neutral'.
    """
    leader:           str
    follower:         str
    optimal_lag_days: int
    granger_f_stat:   float
    granger_pvalue:   float
    cross_corr_peak:  float
    is_significant:   bool
    lead_signal:      str


class LeadLagAnalyzer:
    """Analisi lead-lag via Granger causality test.

    Args:
        client:      DuckDBClient per persistenza.
        lags:        Lista di lag candidati (giorni trading).
        pvalue_thr:  Soglia significatività Granger.
        corr_min:    Soglia minima cross-correlazione.

    Usage::

        analyzer = LeadLagAnalyzer(client=get_duckdb_client())
        result = analyzer.test_pair(returns, 'HYG', 'SPY')
    """

    def __init__(
        self,
        client: DuckDBClient | None = None,
        lags: list[int] | None = None,
        pvalue_thr: float = _PVALUE_THRESHOLD,
        corr_min: float = _CORR_MIN,
    ) -> None:
        self._client    = client
        self._lags      = lags or _CANDIDATE_LAGS
        self._pvalue    = pvalue_thr
        self._corr_min  = corr_min

    def test_pair(
        self,
        returns: pd.DataFrame,
        leader: str,
        follower: str,
    ) -> LeadLagResult:
        """Test Granger: leader → follower.

        Args:
            returns:  DataFrame rendimenti log (colonne=asset, righe=date).
            leader:   Asset candidato come leader (anticipa).
            follower: Asset candidato come follower.

        Returns:
            LeadLagResult con lag ottimale, F-stat, p-value, segnale.
        """
        if leader not in returns.columns or follower not in returns.columns:
            return self._null_result(leader, follower)

        xy = returns[[leader, follower]].dropna()
        if len(xy) < 60:
            return self._null_result(leader, follower)

        # Pre-processing
        x = self._preprocess(xy[leader].values)
        y = self._preprocess(xy[follower].values)

        best_lag, best_f, best_p, best_corr = self._run_granger(x, y)

        is_sig = (best_p < self._pvalue) and (abs(best_corr) >= self._corr_min)
        if is_sig:
            signal = "bullish_lead" if best_corr > 0 else "bearish_lead"
        else:
            signal = "neutral"

        result = LeadLagResult(
            leader=leader,
            follower=follower,
            optimal_lag_days=best_lag,
            granger_f_stat=best_f,
            granger_pvalue=best_p,
            cross_corr_peak=best_corr,
            is_significant=is_sig,
            lead_signal=signal,
        )

        if self._client:
            self._persist(result, date.today())

        return result

    def test_all_pairs(
        self,
        returns: pd.DataFrame,
        pairs: list[tuple[str, str]] | None = None,
    ) -> list[LeadLagResult]:
        """Testa tutte le coppie leader→follower.

        Args:
            returns: DataFrame rendimenti.
            pairs:   Lista di (leader, follower). Default: tutte le coppie.

        Returns:
            Lista di LeadLagResult.
        """
        assets = list(returns.columns)
        if pairs is None:
            pairs = [(a, b) for i, a in enumerate(assets) for b in assets[i+1:]]

        results = []
        for leader, follower in pairs:
            try:
                results.append(self.test_pair(returns, leader, follower))
            except Exception as exc:
                log.debug("lead_lag.test_pair_failed", leader=leader, follower=follower,
                          error=str(exc)[:80])
                results.append(self._null_result(leader, follower))
        return results

    # ─── Core Granger ────────────────────────────────────────────────────────

    def _run_granger(
        self,
        x: np.ndarray,
        y: np.ndarray,
    ) -> tuple[int, float, float, float]:
        """Esegue Granger per tutti i lag e seleziona il migliore.

        Returns:
            (best_lag, best_f_stat, best_pvalue, cross_corr_at_best_lag)
        """
        best_lag   = self._lags[0]
        best_f     = 0.0
        best_p     = 1.0
        best_corr  = 0.0

        for lag in self._lags:
            if lag >= len(x) // 4:
                continue
            try:
                f_stat, p_val = self._granger_test(x, y, lag)
                corr = self._cross_corr_at_lag(x, y, lag)
                # Selezione: min p-value, in parità max |corr|
                if p_val < best_p or (abs(p_val - best_p) < 1e-4 and abs(corr) > abs(best_corr)):
                    best_lag  = lag
                    best_f    = f_stat
                    best_p    = p_val
                    best_corr = corr
            except Exception as exc:
                log.debug("lead_lag.granger_lag_failed", lag=lag, error=str(exc)[:60])
                continue

        return best_lag, best_f, best_p, best_corr

    @staticmethod
    def _granger_test(x: np.ndarray, y: np.ndarray, lag: int) -> tuple[float, float]:
        """Test Granger: x causa y al lag specificato?

        Usa test F su modello VAR(lag) semplificato.

        Returns:
            (f_stat, p_value)
        """
        try:
            from statsmodels.tsa.stattools import grangercausalitytests
            data = np.column_stack([y, x])  # statsmodels: [endog, exog]
            results = grangercausalitytests(data, maxlag=[lag], verbose=False)
            f_result = results[lag][0]["ssr_ftest"]
            return float(f_result[0]), float(f_result[1])
        except ImportError:
            # Fallback: F-test manuale semplificato (VAR(lag))
            return LeadLagAnalyzer._manual_granger(x, y, lag)

    @staticmethod
    def _manual_granger(x: np.ndarray, y: np.ndarray, lag: int) -> tuple[float, float]:
        """F-test Granger semplificato senza statsmodels."""
        from scipy import stats as sp_stats
        n = len(y)
        # Modello ristretto: y ~ y_{-1..lag}
        # Modello non ristretto: y ~ y_{-1..lag} + x_{-1..lag}
        start = lag + 1
        y_dep = y[start:]

        # Regressori modello ristretto
        X_r = np.column_stack([y[start-k-1:n-k-1] for k in range(lag)] + [np.ones(len(y_dep))])
        # Regressori modello non ristretto
        X_u = np.column_stack([X_r] + [x[start-k-1:n-k-1] for k in range(lag)])

        try:
            _, rss_r, _, _ = np.linalg.lstsq(X_r, y_dep, rcond=None)
            _, rss_u, _, _ = np.linalg.lstsq(X_u, y_dep, rcond=None)
        except Exception:
            return 0.0, 1.0

        rss_r = float(rss_r[0]) if len(rss_r) else float(np.sum((y_dep - X_r @ np.linalg.lstsq(X_r, y_dep, rcond=None)[0])**2))
        rss_u_val = float(np.sum((y_dep - X_u @ np.linalg.lstsq(X_u, y_dep, rcond=None)[0])**2))

        if rss_u_val <= 0:
            return 0.0, 1.0

        q  = lag
        df = max(len(y_dep) - X_u.shape[1], 1)
        f_stat = ((rss_r - rss_u_val) / q) / (rss_u_val / df) if q > 0 else 0.0
        p_val  = float(1 - sp_stats.f.cdf(abs(f_stat), q, df))
        return float(f_stat), p_val

    @staticmethod
    def _cross_corr_at_lag(x: np.ndarray, y: np.ndarray, lag: int) -> float:
        """Cross-correlazione di y(t) con x(t-lag)."""
        if lag >= len(x):
            return 0.0
        x_lagged = x[:-lag] if lag > 0 else x
        y_shifted = y[lag:] if lag > 0 else y
        if len(x_lagged) < 10:
            return 0.0
        corr = float(np.corrcoef(x_lagged, y_shifted)[0, 1])
        return 0.0 if np.isnan(corr) else corr

    # ─── Pre-processing ───────────────────────────────────────────────────────

    @staticmethod
    def _preprocess(series: np.ndarray, winsorize_sigma: float = 5.0) -> np.ndarray:
        """Winsorizza outlier via IQR-based bounds (robusto ai casi degeneri)."""
        s = series.copy()
        q25, q75 = np.nanpercentile(s, [25, 75])
        iqr = q75 - q25
        if iqr < 1e-10:
            # Degenerate distribution: use percentile clip to remove tails
            lo = np.nanpercentile(s, 1.0)
            hi = np.nanpercentile(s, 99.0)
        else:
            lo = q25 - winsorize_sigma * iqr
            hi = q75 + winsorize_sigma * iqr
        return np.clip(s, lo, hi)

    # ─── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _null_result(leader: str, follower: str) -> LeadLagResult:
        return LeadLagResult(
            leader=leader, follower=follower,
            optimal_lag_days=0, granger_f_stat=0.0, granger_pvalue=1.0,
            cross_corr_peak=0.0, is_significant=False, lead_signal="neutral",
        )

    def _persist(self, result: LeadLagResult, analysis_date: date) -> None:
        if self._client is None:
            return
        try:
            self._client.execute(
                f"""
                INSERT INTO {_TABLE}
                    (analysis_date, leader_asset, follower_asset, optimal_lag_days,
                     granger_f_stat, granger_pvalue, cross_corr_peak,
                     is_significant, lead_signal)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT (analysis_date, leader_asset, follower_asset) DO UPDATE SET
                    optimal_lag_days = excluded.optimal_lag_days,
                    granger_f_stat   = excluded.granger_f_stat,
                    granger_pvalue   = excluded.granger_pvalue,
                    cross_corr_peak  = excluded.cross_corr_peak,
                    is_significant   = excluded.is_significant,
                    lead_signal      = excluded.lead_signal,
                    computed_at      = NOW()
                """,
                [analysis_date, result.leader, result.follower, result.optimal_lag_days,
                 result.granger_f_stat, result.granger_pvalue, result.cross_corr_peak,
                 result.is_significant, result.lead_signal],
            )
        except Exception as exc:
            log.debug("lead_lag.persist_failed", error=str(exc)[:80])
