"""Black-Scholes calculator — option price + full Greeks.

Implements the closed-form Black-Scholes-Merton model for European options.

Greeks:
  Delta  — dV/dS          (price sensitivity to spot)
  Gamma  — d²V/dS²        (delta sensitivity to spot)
  Vega   — dV/dσ * 0.01   (price sensitivity to 1% vol move)
  Theta  — dV/dt / 365    (price sensitivity to 1 calendar day)
  Rho    — dV/dr * 0.01   (price sensitivity to 1% rate move)

Put-call parity (DoD): C - P = S*exp(-q*T) - K*exp(-r*T)
Batch: 200 options < 200ms (DoD).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.stats import norm

__version__ = "10.0.0"

__all__ = [
    "BSGreeks",
    "BSResult",
    "BlackScholesCalculator",
]

_SQRT_2PI = float(np.sqrt(2.0 * np.pi))


@dataclass(frozen=True)
class BSGreeks:
    delta: float
    gamma: float
    vega:  float    # per 1% move in vol
    theta: float    # per calendar day
    rho:   float    # per 1% move in rate


@dataclass(frozen=True)
class BSResult:
    price:    float
    greeks:   BSGreeks
    option_type: str   # "call" | "put"
    d1:       float
    d2:       float


class BlackScholesCalculator:
    """Black-Scholes-Merton option pricer with full Greeks.

    Usage::

        calc   = BlackScholesCalculator()
        result = calc.price(S=100, K=105, T=0.25, r=0.05, sigma=0.20, q=0.0,
                            option_type="call")
        print(result.price, result.greeks.delta)
    """

    def price(
        self,
        S:    float,          # Spot price
        K:    float,          # Strike price
        T:    float,          # Time to expiry in years
        r:    float,          # Risk-free rate (annualised, e.g. 0.05 = 5%)
        sigma: float,         # Implied volatility (annualised, e.g. 0.20 = 20%)
        q:    float = 0.0,    # Continuous dividend yield
        option_type: str = "call",
    ) -> BSResult:
        """Compute BS price and Greeks for a single option."""
        if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
            return self._zero_result(option_type)

        d1, d2 = self._d1_d2(S, K, T, r, sigma, q)

        if option_type == "call":
            price  = S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
            delta  = float(np.exp(-q * T) * norm.cdf(d1))
            rho    = float(K * T * np.exp(-r * T) * norm.cdf(d2) * 0.01)
        else:
            price  = K * np.exp(-r * T) * norm.cdf(-d2) - S * np.exp(-q * T) * norm.cdf(-d1)
            delta  = float(-np.exp(-q * T) * norm.cdf(-d1))
            rho    = float(-K * T * np.exp(-r * T) * norm.cdf(-d2) * 0.01)

        gamma  = float(norm.pdf(d1) * np.exp(-q * T) / (S * sigma * np.sqrt(T)))
        vega   = float(S * np.exp(-q * T) * norm.pdf(d1) * np.sqrt(T) * 0.01)

        # Theta per calendar day
        theta_common = (
            -S * np.exp(-q * T) * norm.pdf(d1) * sigma / (2.0 * np.sqrt(T))
        )
        if option_type == "call":
            theta = float((theta_common - r * K * np.exp(-r * T) * norm.cdf(d2) +
                          q * S * np.exp(-q * T) * norm.cdf(d1)) / 365.0)
        else:
            theta = float((theta_common + r * K * np.exp(-r * T) * norm.cdf(-d2) -
                          q * S * np.exp(-q * T) * norm.cdf(-d1)) / 365.0)

        return BSResult(
            price       = float(price),
            greeks      = BSGreeks(
                delta = delta,
                gamma = gamma,
                vega  = vega,
                theta = theta,
                rho   = rho,
            ),
            option_type = option_type,
            d1          = float(d1),
            d2          = float(d2),
        )

    def price_batch(
        self,
        options: list[dict[str, Any]],
    ) -> list[BSResult]:
        """Price a batch of options. Target: 200 options < 200ms."""
        return [self.price(**opt) for opt in options]

    # ── Internal ───────────────────────────────────────────────────────────

    @staticmethod
    def _d1_d2(
        S: float, K: float, T: float, r: float, sigma: float, q: float,
    ) -> tuple[float, float]:
        d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        return float(d1), float(d2)

    @staticmethod
    def _zero_result(option_type: str) -> BSResult:
        return BSResult(
            price       = 0.0,
            greeks      = BSGreeks(delta=0.0, gamma=0.0, vega=0.0, theta=0.0, rho=0.0),
            option_type = option_type,
            d1          = 0.0,
            d2          = 0.0,
        )

    def put_call_parity_check(
        self,
        S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0,
    ) -> float:
        """Return |C - P - (S*e^(-qT) - K*e^(-rT))|. Should be < 1e-6."""
        call = self.price(S, K, T, r, sigma, q, "call").price
        put  = self.price(S, K, T, r, sigma, q, "put").price
        lhs  = call - put
        rhs  = S * np.exp(-q * T) - K * np.exp(-r * T)
        return float(abs(lhs - rhs))
