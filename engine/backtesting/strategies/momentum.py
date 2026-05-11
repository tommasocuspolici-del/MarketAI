"""Momentum / breakout strategy.

Long when the n-day return is positive AND price is above the n-day high.
Idea: ride trends by entering only when momentum is confirmed by a
breakout. Vectorized end-to-end (Rule 23).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from engine.backtesting.strategy import Strategy, StrategySignal

if TYPE_CHECKING:
    import pandas as pd

__version__ = "6.0.0"

__all__ = ["Momentum"]


class Momentum(Strategy):
    """N-day return positive + price above N-day rolling high."""

    def __init__(
        self,
        lookback: int = 60,
        require_breakout: bool = True,
    ) -> None:
        self._lookback = lookback
        self._require_breakout = require_breakout

    @property
    def name(self) -> str:
        suffix = "_breakout" if self._require_breakout else ""
        return f"Momentum_{self._lookback}{suffix}"

    def generate_signals(self, ohlcv: pd.DataFrame) -> StrategySignal:
        close = self._ensure_close(ohlcv)
        if len(close) <= self._lookback:
            return self._zero_signal(ohlcv.index, self.name, self._params())

        # n-day return: (close_t / close_{t-n}) - 1
        n = self._lookback
        past_close = close.shift(n)
        n_day_return = (close / past_close) - 1.0
        positive_momentum = (n_day_return > 0.0).astype("float64")

        if self._require_breakout:
            # Long solo se prezzo SOPRA il rolling high — escludiamo l'ultimo
            # giorno per evitare di confrontare il close con se stesso
            rolling_high = close.shift(1).rolling(window=n, min_periods=n).max()
            breakout = (close > rolling_high).astype("float64")
            positions = positive_momentum * breakout
        else:
            positions = positive_momentum

        positions = positions.fillna(0.0)
        return StrategySignal(
            positions=positions,
            name=self.name,
            params=self._params(),
        )

    def _params(self) -> dict[str, float | int | str]:
        return {
            "lookback": self._lookback,
            "require_breakout": int(self._require_breakout),
        }
