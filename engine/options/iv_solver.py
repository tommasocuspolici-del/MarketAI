"""IVSolver — Implied Volatility via Newton-Raphson iteration.

Given a market option price, finds the implied volatility σ* such that
BS(S, K, T, r, σ*) = market_price.

Algorithm:
  1. Initial guess: Brenner-Subrahmanyam approximation
  2. Newton-Raphson iterations: σ_next = σ - (BS(σ) - price) / vega(σ)
  3. Fallback: Brent's method if NR fails to converge

DoD: round-trip BS price → IV → BS price, error < 0.001 on 100 cases.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import brentq

from engine.options.bs_calculator import BlackScholesCalculator

__version__ = "10.0.0"

__all__ = [
    "IVResult",
    "IVSolver",
]

_MAX_ITER   = 100
_TOLERANCE  = 1e-8
_MIN_SIGMA  = 1e-6
_MAX_SIGMA  = 10.0


@dataclass(frozen=True)
class IVResult:
    iv:          float        # Implied volatility (annualised)
    converged:   bool
    iterations:  int
    price_error: float        # |BS(iv) - market_price|
    method:      str          # "newton_raphson" | "brent" | "failed"


class IVSolver:
    """Newton-Raphson IV solver with Brent fallback.

    Usage::

        solver = IVSolver()
        result = solver.solve(
            market_price=5.50, S=100, K=105, T=0.25,
            r=0.05, option_type="call",
        )
        print(result.iv, result.converged)
    """

    def __init__(self, max_iter: int = _MAX_ITER, tol: float = _TOLERANCE) -> None:
        self._max_iter = max_iter
        self._tol      = tol
        self._calc     = BlackScholesCalculator()

    def solve(
        self,
        market_price: float,
        S:            float,
        K:            float,
        T:            float,
        r:            float,
        q:            float = 0.0,
        option_type:  str   = "call",
    ) -> IVResult:
        """Find IV for a given market option price."""
        if market_price <= 0 or T <= 0 or S <= 0:
            return IVResult(iv=float("nan"), converged=False, iterations=0,
                            price_error=float("nan"), method="failed")

        # Initial guess: Brenner-Subrahmanyam approximation
        sigma = float(np.sqrt(2 * np.pi / T) * market_price / S)
        sigma = float(np.clip(sigma, 0.01, 3.0))

        # Newton-Raphson
        for i in range(self._max_iter):
            result = self._calc.price(S, K, T, r, sigma, q, option_type)
            price_diff = result.price - market_price
            vega_raw   = result.greeks.vega / 0.01    # undo the 0.01 scaling

            if abs(price_diff) < self._tol:
                return IVResult(
                    iv          = sigma,
                    converged   = True,
                    iterations  = i + 1,
                    price_error = abs(price_diff),
                    method      = "newton_raphson",
                )

            if abs(vega_raw) < 1e-10:
                break    # vega too small → switch to Brent

            sigma -= price_diff / vega_raw
            sigma  = float(np.clip(sigma, _MIN_SIGMA, _MAX_SIGMA))

        # Brent fallback
        return self._brent_solve(market_price, S, K, T, r, q, option_type)

    def solve_batch(
        self,
        contracts: list[dict[str, Any]],
    ) -> list[IVResult]:
        """Solve IV for a batch of contracts."""
        return [self.solve(**c) for c in contracts]

    # ── Internal ───────────────────────────────────────────────────────────

    def _brent_solve(
        self, market_price: float, S: float, K: float, T: float,
        r: float, q: float, option_type: str,
    ) -> IVResult:
        def objective(sigma: float) -> float:
            return self._calc.price(S, K, T, r, sigma, q, option_type).price - market_price

        try:
            # Check bracket
            if objective(_MIN_SIGMA) * objective(_MAX_SIGMA) > 0:
                return IVResult(iv=float("nan"), converged=False, iterations=self._max_iter,
                                price_error=float("nan"), method="failed")

            iv = float(brentq(objective, _MIN_SIGMA, _MAX_SIGMA,
                              xtol=self._tol, maxiter=self._max_iter))
            err = abs(self._calc.price(S, K, T, r, iv, q, option_type).price - market_price)
            return IVResult(iv=iv, converged=True, iterations=self._max_iter,
                            price_error=err, method="brent")
        except Exception:
            return IVResult(iv=float("nan"), converged=False, iterations=self._max_iter,
                            price_error=float("nan"), method="failed")
