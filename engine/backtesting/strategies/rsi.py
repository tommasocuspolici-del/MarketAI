"""RSI mean-reversion strategy.

Standard contrarian rules on the Relative Strength Index:
  · long when RSI < oversold_threshold (default 30)
  · flat when neutral
  · optional short when RSI > overbought_threshold (default 70)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from engine.backtesting.strategy import Strategy, StrategySignal
from shared.exceptions import BacktestError

if TYPE_CHECKING:
    import pandas as pd

__version__ = "6.0.0"

__all__ = ["RSIMeanReversion", "compute_rsi"]


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI implementation (vectorized).

    RSI = 100 - 100 / (1 + RS) where RS = avg_gain / avg_loss
    Uses simple rolling mean (close-enough approximation of Wilder smoothing
    for daily data — vectorized via pandas, NO Python loops as per Rule 8/23).
    """
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    # Protezione divisione per zero: se avg_loss=0 → RSI=100 (overbought puro)
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    # Quando avg_loss=0 (mai una loss): RSI = 100
    rsi = rsi.where(avg_loss > 0, 100.0)
    return rsi


class RSIMeanReversion(Strategy):
    """RSI < oversold → long; RSI > overbought → short (optional)."""

    def __init__(
        self,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        allow_short: bool = False,
    ) -> None:
        if not 0.0 < oversold < overbought < 100.0:
            raise BacktestError(
                f"thresholds must satisfy 0 < oversold ({oversold}) "
                f"< overbought ({overbought}) < 100"
            )
        self._period = period
        self._oversold = oversold
        self._overbought = overbought
        self._allow_short = allow_short

    @property
    def name(self) -> str:
        return f"RSI_{self._period}_{int(self._oversold)}_{int(self._overbought)}"

    def generate_signals(self, ohlcv: pd.DataFrame) -> StrategySignal:
        close = self._ensure_close(ohlcv)
        if len(close) <= self._period:
            return self._zero_signal(ohlcv.index, self.name, self._params())

        rsi = compute_rsi(close, self._period)

        # Posizioni vettorizzate (Regola 23: zero loop)
        long_mask = (rsi < self._oversold).astype("float64")
        if self._allow_short:
            short_mask = (rsi > self._overbought).astype("float64")
            positions = long_mask - short_mask
        else:
            positions = long_mask

        positions = positions.fillna(0.0)
        return StrategySignal(
            positions=positions,
            name=self.name,
            params=self._params(),
        )

    def _params(self) -> dict[str, float | int | str]:
        return {
            "period": self._period,
            "oversold": self._oversold,
            "overbought": self._overbought,
            "allow_short": int(self._allow_short),
        }
