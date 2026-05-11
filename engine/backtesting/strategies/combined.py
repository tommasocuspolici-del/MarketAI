"""Combined multi-factor strategy.

Aggregates signals from multiple sub-strategies via voting:
  · ``mode="all"``  → AND logic: position only if ALL sub-strategies agree
  · ``mode="any"``  → OR logic: position if ANY sub-strategy fires
  · ``mode="mean"`` → average of positions (continuous in [-1, 1])

Vectorized end-to-end (Rule 23). Useful for cleaning up false signals
of a single approach.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine.backtesting.strategy import Strategy, StrategySignal
from shared.exceptions import BacktestError

__version__ = "6.0.0"

__all__ = ["CombinedStrategy"]


class CombinedStrategy(Strategy):
    """Combine multiple sub-strategies into a single signal."""

    def __init__(
        self,
        sub_strategies: list[Strategy],
        mode: str = "mean",
    ) -> None:
        if not sub_strategies:
            raise BacktestError("CombinedStrategy needs at least one sub-strategy")
        if mode not in ("all", "any", "mean"):
            raise BacktestError(f"invalid mode '{mode}'")
        self._subs = sub_strategies
        self._mode = mode

    @property
    def name(self) -> str:
        sub_names = "+".join(s.name for s in self._subs)
        return f"Combined[{self._mode}]({sub_names})"

    def generate_signals(self, ohlcv: pd.DataFrame) -> StrategySignal:
        # Ottieni i segnali di tutte le sub-strategie
        sub_sigs = [s.generate_signals(ohlcv) for s in self._subs]
        # Stack vettorizzato: shape (n_strategies, n_bars)
        stacked = np.stack(
            [sig.positions.to_numpy(dtype="float64") for sig in sub_sigs], axis=0
        )

        if self._mode == "mean":
            combined = stacked.mean(axis=0)
        elif self._mode == "all":
            # Tutti devono avere lo stesso segno e magnitudine ≥ 0.5
            sign_match = np.all(np.sign(stacked) == np.sign(stacked[0:1, :]), axis=0)
            magnitude_ok = np.all(np.abs(stacked) >= 0.5, axis=0)
            agree_mask = (sign_match & magnitude_ok).astype("float64")
            combined = stacked[0, :] * agree_mask
        else:  # "any"
            # Almeno uno fires (>0.5 in valore assoluto): usa il segno medio
            any_fires = (np.abs(stacked) >= 0.5).any(axis=0).astype("float64")
            mean_signal = stacked.mean(axis=0)
            combined = np.sign(mean_signal) * any_fires

        # Clip difensivo in [-1, 1] (post-condition contrattuale)
        combined = np.clip(combined, -1.0, 1.0)

        return StrategySignal(
            positions=pd.Series(combined, index=ohlcv.index, dtype="float64"),
            name=self.name,
            params={"mode": self._mode, "n_sub": len(self._subs)},
        )
