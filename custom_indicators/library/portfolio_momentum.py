"""PortfolioMomentum — composite portfolio momentum (#2).

Output: [-1, 1]
  > 0 → positive momentum (portfolio outperforming trend)
  < 0 → negative momentum
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from shared.signal_types import SIGNAL_CUSTOM_PREFIX, Signal

__version__ = "10.0.0"

__all__ = ["PortfolioMomentumIndicator", "MomentumResult"]

_WINDOW_DEFAULT = 63    # ~3 months trading days


@dataclass
class MomentumResult:
    momentum_1m:    float    # 21-day return
    momentum_3m:    float    # 63-day return
    composite:      float    # [-1, 1] weighted composite
    signal_value:   float    # same as composite, clamped


class PortfolioMomentumIndicator:
    """Pre-built #2 — Portfolio composite momentum (1M + 3M).

    Args:
        window_days: Primary momentum window (default 63 = 3 months)
    """

    def __init__(self, window_days: int = _WINDOW_DEFAULT) -> None:
        self._window = window_days

    def compute(self, portfolio_returns: list[float] | None = None) -> MomentumResult:
        """Compute momentum signal from portfolio daily returns.

        Args:
            portfolio_returns: List of daily portfolio returns (float).
        """
        if not portfolio_returns or len(portfolio_returns) < 21:
            return MomentumResult(0.0, 0.0, 0.0, 0.0)

        arr = np.array(portfolio_returns, dtype=np.float64)

        # Cumulative returns over windows
        mom_1m = float(np.sum(arr[-21:])) if len(arr) >= 21 else 0.0
        mom_3m = float(np.sum(arr[-self._window:])) if len(arr) >= self._window else mom_1m

        # Normalise to [-1, 1]: assume ±15% is extreme (3σ for a ~5% vol portfolio)
        _NORM = 0.15
        norm_1m = float(np.clip(mom_1m / _NORM, -1.0, 1.0))
        norm_3m = float(np.clip(mom_3m / _NORM, -1.0, 1.0))

        composite    = float(0.4 * norm_1m + 0.6 * norm_3m)
        signal_value = float(np.clip(composite, -1.0, 1.0))

        return MomentumResult(
            momentum_1m  = round(mom_1m, 4),
            momentum_3m  = round(mom_3m, 4),
            composite    = round(composite, 4),
            signal_value = round(signal_value, 4),
        )

    def to_signal(self, result: MomentumResult) -> Signal:
        return Signal(
            name          = f"{SIGNAL_CUSTOM_PREFIX}portfolio_momentum",
            value         = result.signal_value,
            confidence    = 0.7,
            source_module = __name__,
            metadata      = {"mom_1m": result.momentum_1m, "mom_3m": result.momentum_3m},
        )
