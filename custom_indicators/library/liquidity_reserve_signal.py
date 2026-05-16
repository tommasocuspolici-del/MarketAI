"""LiquidityReserveSignal — minimum cash reserve adequacy (#6).

Checks whether the portfolio cash reserve covers the minimum required months
of living expenses. Returns a positive signal when reserve is adequate.

Output: [-1, 1]
  > 0 → cash reserve above minimum (can invest)
  < 0 → cash reserve below minimum (should not invest, rebuild first)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from shared.signal_types import SIGNAL_CUSTOM_PREFIX, Signal

__version__ = "10.0.0"

__all__ = ["LiquidityReserveSignal", "LiquidityResult"]

_MIN_MONTHS_DEFAULT    = 3.0
_TARGET_MONTHS_DEFAULT = 6.0


@dataclass
class LiquidityResult:
    cash_months:    float    # Current cash reserve in months of expenses
    min_months:     float    # Minimum required
    target_months:  float    # Target (fully funded)
    adequacy_ratio: float    # cash / target [0, ∞)
    signal_value:   float    # [-1, 1]


class LiquidityReserveSignal:
    """Pre-built #6 — liquidity reserve adequacy signal.

    Args:
        min_months:    Minimum months of expenses to keep in cash (default 3).
        target_months: Target reserve in months (default 6).
    """

    def __init__(
        self,
        min_months:    float = _MIN_MONTHS_DEFAULT,
        target_months: float = _TARGET_MONTHS_DEFAULT,
    ) -> None:
        self._min    = min_months
        self._target = target_months

    def compute(self, cash_reserve_months: float = 0.0) -> LiquidityResult:
        """Compute liquidity signal.

        Args:
            cash_reserve_months: Current cash in months of monthly expenses.
        """
        adequacy = float(cash_reserve_months / self._target) if self._target > 0 else 0.0

        if cash_reserve_months < self._min:
            signal_value = float(np.clip((cash_reserve_months / self._min - 1.0), -1.0, 0.0))
        else:
            headroom = (cash_reserve_months - self._min) / (self._target - self._min + 1e-9)
            signal_value = float(np.clip(headroom, 0.0, 1.0))

        return LiquidityResult(
            cash_months    = round(cash_reserve_months, 2),
            min_months     = self._min,
            target_months  = self._target,
            adequacy_ratio = round(adequacy, 4),
            signal_value   = round(signal_value, 4),
        )

    def to_signal(self, result: LiquidityResult) -> Signal:
        return Signal(
            name          = f"{SIGNAL_CUSTOM_PREFIX}liquidity_reserve",
            value         = result.signal_value,
            confidence    = float(np.clip(result.adequacy_ratio, 0.0, 1.0)),
            source_module = __name__,
            metadata      = {
                "cash_months":   result.cash_months,
                "min_months":    result.min_months,
                "target_months": result.target_months,
            },
        )
