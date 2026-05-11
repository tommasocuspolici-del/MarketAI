"""Moving Average Crossover strategy (long-only by default).

Classic dual-MA strategy:
  · long when fast SMA > slow SMA
  · flat when fast SMA <= slow SMA
  · optional symmetric short version
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from engine.backtesting.strategy import Strategy, StrategySignal

if TYPE_CHECKING:
    import pandas as pd

__version__ = "6.0.0"

__all__ = ["MovingAverageCrossover"]


class MovingAverageCrossover(Strategy):
    """SMA(fast) vs SMA(slow) crossover."""

    def __init__(
        self,
        fast: int = 20,
        slow: int = 50,
        allow_short: bool = False,
    ) -> None:
        if fast >= slow:
            from shared.exceptions import BacktestError

            raise BacktestError(
                f"fast period ({fast}) must be < slow period ({slow})"
            )
        self._fast = fast
        self._slow = slow
        self._allow_short = allow_short

    @property
    def name(self) -> str:
        return f"MA_cross_{self._fast}_{self._slow}"

    def generate_signals(self, ohlcv: pd.DataFrame) -> StrategySignal:
        close = self._ensure_close(ohlcv)
        if len(close) <= self._slow:
            return self._zero_signal(ohlcv.index, self.name, self._params())

        # SMA vettorizzate (Regola 8: numpy/pandas, zero loop)
        fast_sma = close.rolling(window=self._fast, min_periods=self._fast).mean()
        slow_sma = close.rolling(window=self._slow, min_periods=self._slow).mean()

        # Posizione raw: +1 se fast>slow, 0 altrimenti (o -1 se short permesso)
        long_mask = (fast_sma > slow_sma).astype("float64")
        if self._allow_short:
            short_mask = (fast_sma < slow_sma).astype("float64")
            positions = long_mask - short_mask
        else:
            positions = long_mask

        # NaN del warm-up SMA → 0 (flat)
        positions = positions.fillna(0.0)

        return StrategySignal(
            positions=positions,
            name=self.name,
            params=self._params(),
        )

    def _params(self) -> dict[str, float | int | str]:
        return {
            "fast": self._fast,
            "slow": self._slow,
            "allow_short": int(self._allow_short),
        }
