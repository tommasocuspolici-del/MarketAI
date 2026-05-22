"""Volatility Risk Premium Calculator.

VRP = IV_ATM_30d - RV_30d (realized volatility)
Positivo → mercato paga premium per protezione (volatilità cara)
Negativo → IV < RV (raro, short vol è attraente)

Signal [-1, +1]:
  VRP alto (z-score > 1) → vol cara → signal = -1 (sell vol)
  VRP basso (z-score < -1) → vol economica → signal = +1 (buy vol)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from shared.logger import get_logger

__version__ = "11.0.0"

__all__ = ["VRPCalculator", "VRPResult"]

log = get_logger(__name__)

TABLE_VRP = "vrp_daily"
RV_WINDOW: int = 21              # 21 giorni trading ≈ 1 mese
ANNUALIZATION_FACTOR: float = 252.0
SIGNAL_Z_THRESHOLD: float = 1.0  # z-score ±1 per saturazione segnale


@dataclass
class VRPResult:
    """Risultato calcolo VRP per un singolo asset."""

    ticker: str
    snapshot_date: date
    iv_atm_30d: float          # IV implicita ATM 30gg (annualizzata)
    rv_30d: float              # Realized Volatility 30gg (annualizzata)
    vrp: float                 # iv_atm_30d - rv_30d
    vrp_zscore: float          # z-score su storia
    signal: float              # [-1,+1]: -1=vol cara, +1=vol economica
    is_reliable: bool          # True if rv_window data disponibile


class VRPCalculator:
    """Calcola Volatility Risk Premium da IV e prezzi storici."""

    def compute(
        self,
        ticker: str,
        iv_series: pd.Series,
        price_series: pd.Series,
        zscore_window: int = 252,
    ) -> VRPResult:
        """Calcola VRP per un singolo asset.

        Parameters
        ----------
        ticker:
            Simbolo dell'asset.
        iv_series:
            Serie IV ATM 30gg annualizzata, index=date.
        price_series:
            Serie prezzi close, index=date.
        zscore_window:
            Finestra per calcolo z-score VRP (default: 252 giorni).
        """
        # IV corrente: ultimo valore disponibile
        if iv_series.empty:
            log.warning("vrp.empty_iv_series", ticker=ticker)
            return self._empty_result(ticker)

        iv_atm = float(iv_series.iloc[-1])
        snapshot_dt = iv_series.index[-1]
        snap_date = snapshot_dt.date() if hasattr(snapshot_dt, "date") else date.today()

        # Realized Vol
        rv = self._realized_vol(price_series, window=RV_WINDOW)
        is_reliable = len(price_series.dropna()) >= RV_WINDOW

        vrp = iv_atm - rv

        # Z-score su storia VRP
        vrp_history = self._compute_vrp_history(iv_series, price_series, RV_WINDOW)
        vrp_zscore = self._vrp_zscore(vrp, vrp_history, zscore_window)

        # Signal [-1, +1]: clipping con soglia ±1 z-score
        signal = float(np.clip(-vrp_zscore / SIGNAL_Z_THRESHOLD, -1.0, 1.0))

        log.info(
            "vrp.computed",
            ticker=ticker,
            iv_atm=round(iv_atm, 4),
            rv_30d=round(rv, 4),
            vrp=round(vrp, 4),
            vrp_zscore=round(vrp_zscore, 2),
            signal=round(signal, 2),
        )

        return VRPResult(
            ticker=ticker,
            snapshot_date=snap_date,
            iv_atm_30d=iv_atm,
            rv_30d=rv,
            vrp=vrp,
            vrp_zscore=vrp_zscore,
            signal=signal,
            is_reliable=is_reliable,
        )

    def compute_batch(
        self,
        tickers: list[str],
        iv_data: dict[str, pd.Series],
        price_data: dict[str, pd.Series],
    ) -> list[VRPResult]:
        """Calcola VRP per una lista di asset."""
        results: list[VRPResult] = []
        for ticker in tickers:
            if ticker not in iv_data or ticker not in price_data:
                log.warning("vrp.missing_data", ticker=ticker)
                results.append(self._empty_result(ticker))
                continue
            result = self.compute(ticker, iv_data[ticker], price_data[ticker])
            results.append(result)
        return results

    def _realized_vol(self, prices: pd.Series, window: int = RV_WINDOW) -> float:
        """RV = sqrt(252) * std(log_returns) su finestra mobile."""
        prices_clean = prices.dropna()
        if len(prices_clean) < 2:
            return 0.0

        log_rets = np.log(prices_clean / prices_clean.shift(1)).dropna()
        if len(log_rets) < window:
            window = len(log_rets)
        if window < 2:
            return 0.0

        rv = float(np.std(log_rets.iloc[-window:].to_numpy(dtype=float), ddof=1))
        return rv * np.sqrt(ANNUALIZATION_FACTOR)

    def _compute_vrp_history(
        self,
        iv_series: pd.Series,
        price_series: pd.Series,
        window: int,
    ) -> pd.Series:
        """Calcola serie storica VRP: IV[t] - RV_rolling[t]."""
        prices_clean = price_series.dropna()
        if len(prices_clean) < 2:
            return pd.Series(dtype=float)

        log_rets = np.log(prices_clean / prices_clean.shift(1)).dropna()
        rv_rolling = log_rets.rolling(window=window, min_periods=2).std() * np.sqrt(ANNUALIZATION_FACTOR)

        common = iv_series.index.intersection(rv_rolling.index)
        if len(common) == 0:
            return pd.Series(dtype=float)

        return iv_series.reindex(common) - rv_rolling.reindex(common)

    def _vrp_zscore(
        self,
        vrp: float,
        vrp_history: pd.Series,
        window: int = 252,
    ) -> float:
        """Z-score del VRP corrente rispetto alla storia."""
        hist = vrp_history.dropna()
        if len(hist) < 2:
            return 0.0

        if len(hist) > window:
            hist = hist.iloc[-window:]

        mu = float(hist.mean())
        sigma = float(hist.std(ddof=1))
        if sigma < 1e-10:
            return 0.0

        return (vrp - mu) / sigma

    @staticmethod
    def _empty_result(ticker: str) -> VRPResult:
        return VRPResult(
            ticker=ticker,
            snapshot_date=date.today(),
            iv_atm_30d=0.0,
            rv_30d=0.0,
            vrp=0.0,
            vrp_zscore=0.0,
            signal=0.0,
            is_reliable=False,
        )
