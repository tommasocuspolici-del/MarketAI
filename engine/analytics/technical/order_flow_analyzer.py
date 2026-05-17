"""OrderFlowAnalyzer — Cumulative Volume Delta (CVD) and buy/sell imbalance.

CVD (Cumulative Volume Delta):
  Running sum of (buy_volume - sell_volume) over time.
  Rising CVD → buyers dominating (bullish pressure)
  Falling CVD → sellers dominating (bearish pressure)
  CVD divergence from price → potential reversal signal

Buy/Sell volume estimation from OHLC (no tick data required):
  If close > open: assumed buy-dominant — buy_vol = volume * close_pos
  If close < open: assumed sell-dominant — sell_vol = volume * (1 - close_pos)
  where close_pos = (close - low) / (high - low + ε)  ∈ [0,1]

This is a widely-used approximation (Hawkes/Bierwag method).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

from shared.logger import get_logger

__version__ = "10.0.0"

__all__ = [
    "OrderFlowResult",
    "OrderFlowAnalyzer",
]

log = get_logger(__name__)


@dataclass
class OrderFlowResult:
    cvd:             npt.NDArray[np.float64]   # Cumulative Volume Delta time series
    cvd_last:        float        # Latest CVD value
    cvd_change_pct:  float        # CVD change over lookback window (%)
    delta_ratio:     float        # buy_vol / total_vol ∈ [0, 1]
    signal:          float        # [-1, 1]: buy pressure vs sell pressure
    divergence:      bool         # True if CVD and price diverge
    n_bars:          int


class OrderFlowAnalyzer:
    """Compute order flow metrics from OHLCV data.

    Args:
        lookback:  Window for CVD change computation (default 20 bars).
    """

    def __init__(self, lookback: int = 20) -> None:
        self._lookback = lookback

    def analyze(self, ohlcv: pd.DataFrame) -> OrderFlowResult:
        """Compute CVD and delta imbalance.

        Args:
            ohlcv: DataFrame with 'open', 'high', 'low', 'close', 'volume'.

        Returns:
            OrderFlowResult with CVD time series and signal.
        """
        ohlcv = ohlcv.dropna(subset=["open", "high", "low", "close", "volume"])
        if len(ohlcv) < 2:
            return self._empty_result()

        opens   = ohlcv["open"].values.astype(np.float64)
        highs   = ohlcv["high"].values.astype(np.float64)
        lows    = ohlcv["low"].values.astype(np.float64)
        closes  = ohlcv["close"].values.astype(np.float64)
        volumes = ohlcv["volume"].values.astype(np.float64)

        # Estimate buy fraction per bar (close position in bar range)
        ranges     = highs - lows
        ranges     = np.where(ranges < 1e-9, 1e-9, ranges)
        close_pos  = np.clip((closes - lows) / ranges, 0.0, 1.0)

        buy_vol    = volumes * close_pos
        sell_vol   = volumes * (1.0 - close_pos)
        delta      = buy_vol - sell_vol

        cvd        = np.cumsum(delta)
        cvd_last   = float(cvd[-1])

        # CVD change over lookback window
        lb         = min(self._lookback, len(cvd) - 1)
        cvd_prev   = float(cvd[-lb - 1])
        cvd_chg    = float((cvd_last - cvd_prev) / (abs(cvd_prev) + 1e-9) * 100.0)

        # Delta ratio: overall buy dominance
        total_buy  = float(buy_vol.sum())
        total_vol  = float(volumes.sum())
        ratio      = total_buy / total_vol if total_vol > 0 else 0.5

        # Signal: normalise delta ratio to [-1, 1]
        signal = float(np.clip((ratio - 0.5) * 2.0, -1.0, 1.0))

        # Divergence: price up but CVD down (or vice versa)
        price_dir = closes[-1] - closes[-lb - 1]
        cvd_dir   = cvd_last - cvd_prev
        divergence = bool((price_dir > 0) != (cvd_dir > 0) and abs(price_dir) > 0.001)

        log.debug(
            "order_flow.analyzed",
            cvd_last=round(cvd_last, 2),
            cvd_chg=round(cvd_chg, 2),
            ratio=round(ratio, 3),
            signal=round(signal, 3),
            divergence=divergence,
        )
        return OrderFlowResult(
            cvd            = cvd,
            cvd_last       = round(cvd_last, 2),
            cvd_change_pct = round(cvd_chg, 2),
            delta_ratio    = round(ratio, 4),
            signal         = round(signal, 4),
            divergence     = divergence,
            n_bars         = len(ohlcv),
        )

    @staticmethod
    def _empty_result() -> OrderFlowResult:
        return OrderFlowResult(
            cvd=np.array([0.0]), cvd_last=0.0, cvd_change_pct=0.0,
            delta_ratio=0.5, signal=0.0, divergence=False, n_bars=0,
        )
