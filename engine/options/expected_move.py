"""ExpectedMoveCalculator — 1 standard-deviation expected move from IV.

Formula: EM = IV * spot * sqrt(T)

Where:
  IV    — implied volatility (annualised, e.g. 0.20 = 20%)
  spot  — current spot price
  T     — time to expiry in years

Returns absolute move and percentage, plus the ±1σ price range.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

__version__ = "10.0.0"

__all__ = [
    "ExpectedMoveResult",
    "ExpectedMoveCalculator",
]


@dataclass(frozen=True)
class ExpectedMoveResult:
    spot:           float
    iv:             float       # annualised IV used
    t_years:        float
    move_abs:       float       # 1σ absolute move
    move_pct:       float       # 1σ move as fraction of spot (e.g. 0.10 = 10%)
    upper_1sigma:   float       # spot + move_abs
    lower_1sigma:   float       # spot - move_abs
    upper_2sigma:   float       # spot + 2 * move_abs
    lower_2sigma:   float       # spot - 2 * move_abs


class ExpectedMoveCalculator:
    """Calculate expected price move from implied volatility.

    Usage::

        calc   = ExpectedMoveCalculator()
        result = calc.calculate(spot=100.0, iv=0.20, t_years=0.25)
        print(result.move_abs, result.move_pct)

    Result is the 1-standard-deviation expected move over the period T.
    Probability interpretation: ~68% of outcomes fall within ±1σ.
    """

    def calculate(
        self,
        spot:   float,
        iv:     float,
        t_years: float,
    ) -> ExpectedMoveResult:
        """Compute expected move for given spot, IV, and time horizon.

        Args:
            spot:    Current price of the underlying.
            iv:      Annualised implied volatility (e.g. 0.20 for 20%).
            t_years: Time horizon in years (e.g. 30/365 for 30 days).

        Returns:
            ExpectedMoveResult with absolute and percentage move, ±1σ and ±2σ ranges.
        """
        if spot <= 0 or iv <= 0 or t_years <= 0:
            return ExpectedMoveResult(
                spot=spot, iv=iv, t_years=t_years,
                move_abs=0.0, move_pct=0.0,
                upper_1sigma=spot, lower_1sigma=spot,
                upper_2sigma=spot, lower_2sigma=spot,
            )

        move_abs = iv * spot * math.sqrt(t_years)
        move_pct = move_abs / spot

        return ExpectedMoveResult(
            spot          = spot,
            iv            = iv,
            t_years       = t_years,
            move_abs      = move_abs,
            move_pct      = move_pct,
            upper_1sigma  = spot + move_abs,
            lower_1sigma  = spot - move_abs,
            upper_2sigma  = spot + 2.0 * move_abs,
            lower_2sigma  = spot - 2.0 * move_abs,
        )

    def calculate_days(
        self,
        spot: float,
        iv:   float,
        days: int,
    ) -> ExpectedMoveResult:
        """Convenience wrapper: pass days instead of fractional years."""
        return self.calculate(spot=spot, iv=iv, t_years=days / 365.0)
