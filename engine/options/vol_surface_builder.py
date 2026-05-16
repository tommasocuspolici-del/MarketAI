"""VolSurfaceBuilder — implied volatility surface from option chain data.

Builds a 2-D surface: IV = f(strike, expiry) from a list of option contracts
with market prices. Uses the IVSolver for each contract, then organises
results into a strike × expiry grid.

The surface reveals:
  - Volatility smile/skew: how IV varies across strikes for fixed expiry
  - Term structure: how IV varies across expiries for ATM options
  - IV skew: difference between OTM put IV and OTM call IV (tail risk proxy)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from engine.options.iv_solver import IVSolver

__version__ = "10.0.0"

__all__ = [
    "VolSurface",
    "VolSurfaceBuilder",
]


@dataclass
class VolSurface:
    """Implied volatility surface."""
    strikes:         list[float]           # Sorted unique strikes
    expiries:        list[float]           # Sorted unique expiries (years)
    iv_matrix:       np.ndarray[Any, Any]  # shape (n_expiries, n_strikes), NaN where no data
    atm_iv_by_expiry: dict[float, float]   # ATM IV per expiry
    skew_by_expiry:   dict[float, float]   # 25-delta put IV - 25-delta call IV proxy
    n_contracts:     int


class VolSurfaceBuilder:
    """Build an IV surface from a list of option contracts.

    Usage::

        contracts = [
            {"market_price": 5.5, "S": 100, "K": 100, "T": 0.25,
             "r": 0.05, "q": 0.0, "option_type": "call"},
            ...
        ]
        builder = VolSurfaceBuilder()
        surface = builder.build(contracts, spot=100.0)
    """

    def __init__(self) -> None:
        self._solver = IVSolver()

    def build(self, contracts: list[dict[str, Any]], spot: float) -> VolSurface:
        """Build IV surface from a list of option contract dicts.

        Args:
            contracts: List of dicts with keys:
                       market_price, S, K, T, r, q (optional), option_type
            spot:      Current spot price (for ATM identification).

        Returns:
            VolSurface with IV matrix and summary statistics.
        """
        if not contracts:
            return VolSurface([], [], np.array([]), {}, {}, 0)

        # Solve IV for each contract
        solved: list[tuple[float, float, float]] = []  # (strike, expiry, iv)
        for c in contracts:
            result = self._solver.solve(**{k: v for k, v in c.items()})
            if result.converged and not np.isnan(result.iv):
                solved.append((float(c["K"]), float(c["T"]), result.iv))

        if not solved:
            return VolSurface([], [], np.array([]), {}, {}, 0)

        strikes  = sorted(set(s[0] for s in solved))
        expiries = sorted(set(s[1] for s in solved))

        iv_matrix = np.full((len(expiries), len(strikes)), np.nan)
        for K, T, iv in solved:
            i = expiries.index(T)
            j = strikes.index(K)
            # Take mean if multiple IVs for same (K, T)
            if np.isnan(iv_matrix[i, j]):
                iv_matrix[i, j] = iv
            else:
                iv_matrix[i, j] = (iv_matrix[i, j] + iv) / 2.0

        # ATM IV per expiry (closest strike to spot)
        atm_iv: dict[float, float] = {}
        for i, T in enumerate(expiries):
            row = iv_matrix[i]
            if not np.all(np.isnan(row)):
                atm_j  = int(np.argmin(np.abs(np.array(strikes) - spot)))
                atm_iv[T] = float(row[atm_j]) if not np.isnan(row[atm_j]) else float(np.nanmean(row))

        # Skew proxy: lowest strike IV - highest strike IV per expiry
        skew: dict[float, float] = {}
        for i, T in enumerate(expiries):
            row      = iv_matrix[i]
            valid    = ~np.isnan(row)
            if valid.sum() >= 2:
                skew[T] = float(row[valid][0] - row[valid][-1])   # OTM put - OTM call

        return VolSurface(
            strikes           = strikes,
            expiries          = expiries,
            iv_matrix         = iv_matrix,
            atm_iv_by_expiry  = atm_iv,
            skew_by_expiry    = skew,
            n_contracts       = len(solved),
        )
