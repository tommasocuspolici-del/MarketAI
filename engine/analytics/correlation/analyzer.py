"""Correlation analyzer — rolling correlations + lead-lag detection.

Vectorized via numpy/scipy/statsmodels (Rule 8). DCC-GARCH-lite uses an EWMA
approximation when the heavyweight `arch` library isn't available (controlled
via feature flag `advanced_correlation`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from shared.exceptions import CorrelationError, InsufficientDataError
from shared.logger import get_logger

__version__ = "6.0.0"

__all__ = ["CorrelationAnalyzer", "CorrelationReport", "LeadLagPair"]

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LeadLagPair:
    """Lead-lag relationship between two assets."""

    leader: str
    follower: str
    lag_periods: int
    correlation: float
    p_value: float


@dataclass(frozen=True, slots=True)
class CorrelationReport:
    """Output of CorrelationAnalyzer.run()."""

    static_corr: pd.DataFrame             # Pearson over the full window
    rolling_corr_30d: pd.DataFrame        # last 30d of pairwise rolling corr
    dynamic_corr: pd.DataFrame | None     # DCC-GARCH-lite (EWMA) latest
    lead_lag_pairs: list[LeadLagPair]
    n_assets: int
    n_observations: int


class CorrelationAnalyzer:
    """Multi-asset correlation analyzer.

    Inputs:
        prices: DataFrame with shape (T, N) where columns are tickers and
                index is a UTC-aware DatetimeIndex.

    Outputs:
        CorrelationReport with static, rolling, dynamic correlations + lead-lag.
    """

    MIN_OBS = 60   # Min observations to run dynamic correlations

    def __init__(
        self, ewma_lambda: float = 0.94, lead_lag_max_periods: int = 5
    ) -> None:
        if not 0.0 < ewma_lambda < 1.0:
            raise CorrelationError(
                f"ewma_lambda must be in (0, 1), got {ewma_lambda}"
            )
        self._lambda = ewma_lambda
        self._max_lag = lead_lag_max_periods

    def run(self, prices: pd.DataFrame) -> CorrelationReport:
        """Run the full correlation analysis."""
        if prices.empty:
            raise CorrelationError("empty prices DataFrame")
        if prices.shape[1] < 2:
            raise CorrelationError("need at least 2 assets")

        # Convert to log returns (Rule 8: numpy vectorized)
        returns = np.log(prices / prices.shift(1)).dropna()
        if len(returns) < self.MIN_OBS:
            raise InsufficientDataError(self.MIN_OBS, len(returns))

        # 1. Static correlation (Pearson over the full window)
        static_corr = returns.corr()

        # 2. Rolling 30-day pairwise correlation — most recent value
        window = min(30, len(returns))
        rolling = returns.rolling(window=window).corr().dropna()
        # Last "frame" of rolling correlations
        last_date = rolling.index.get_level_values(0).max()
        rolling_30d = rolling.loc[last_date]

        # 3. DCC-GARCH-lite via EWMA (vectorized)
        dynamic_corr = self._ewma_correlation(returns)

        # 4. Lead-lag detection
        lead_lag = self._detect_lead_lag(returns)

        log.info(
            "correlation.completed",
            n_assets=prices.shape[1],
            n_obs=len(returns),
            n_lead_lag=len(lead_lag),
        )

        return CorrelationReport(
            static_corr=static_corr,
            rolling_corr_30d=rolling_30d,
            dynamic_corr=dynamic_corr,
            lead_lag_pairs=lead_lag,
            n_assets=prices.shape[1],
            n_observations=len(returns),
        )

    def _ewma_correlation(self, returns: pd.DataFrame) -> pd.DataFrame:
        """EWMA-based dynamic correlation (DCC-GARCH-lite).

        For each pair (i, j):
            cov_ij[t] = λ * cov_ij[t-1] + (1-λ) * r_i[t] * r_j[t]
            corr_ij[t] = cov_ij[t] / sqrt(cov_ii[t] * cov_jj[t])

        Returns the latest correlation matrix only (not the full path).
        """
        n_obs, _n_assets = returns.shape
        r = returns.to_numpy()
        # Center returns
        r_centered = r - r.mean(axis=0)
        # Initial covariance = sample covariance
        cov = np.cov(r_centered.T, ddof=0)
        for t in range(n_obs):
            outer = np.outer(r_centered[t], r_centered[t])
            cov = self._lambda * cov + (1 - self._lambda) * outer
        # Convert to correlation
        std = np.sqrt(np.diag(cov))
        denom = np.outer(std, std)
        # Avoid divide by zero
        denom[denom == 0] = np.nan
        corr = cov / denom
        return pd.DataFrame(corr, index=returns.columns, columns=returns.columns)

    def _detect_lead_lag(
        self, returns: pd.DataFrame
    ) -> list[LeadLagPair]:
        """Detect lead-lag relationships using cross-correlation.

        For each pair (a, b), find the lag k in [1, max_lag] maximizing
        |corr(a[t], b[t+k])|. If exceeds threshold, mark as lead-lag.
        """
        pairs: list[LeadLagPair] = []
        cols = list(returns.columns)
        threshold = 0.20      # Minimum |corr| to register a pair
        for i, a in enumerate(cols):
            for b in cols[i + 1:]:
                best_corr = 0.0
                best_lag = 0
                best_leader = a
                best_follower = b
                for k in range(1, self._max_lag + 1):
                    # a leads b: corr(a[t-k], b[t]) = corr(a.shift(k), b)
                    corr_ab = float(
                        returns[a].shift(k).corr(returns[b])
                    )
                    corr_ba = float(
                        returns[b].shift(k).corr(returns[a])
                    )
                    if abs(corr_ab) > abs(best_corr):
                        best_corr = corr_ab
                        best_lag = k
                        best_leader, best_follower = a, b
                    if abs(corr_ba) > abs(best_corr):
                        best_corr = corr_ba
                        best_lag = k
                        best_leader, best_follower = b, a
                if abs(best_corr) >= threshold and best_lag > 0:
                    # Approx p-value from |z| with N obs (no lag-aware adjust.)
                    # p = 2*(1 - Phi(|z|*sqrt(N))). Use scipy normal CDF if needed.
                    n = len(returns)
                    z = abs(best_corr) * np.sqrt(max(n - best_lag, 1))
                    p = float(2.0 * (1.0 - _norm_cdf(z)))
                    pairs.append(LeadLagPair(
                        leader=best_leader,
                        follower=best_follower,
                        lag_periods=best_lag,
                        correlation=best_corr,
                        p_value=p,
                    ))
        return pairs


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via math.erf (no scipy dependency at this layer)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
