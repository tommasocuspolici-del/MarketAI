"""MockOptionsChain — synthetic option chain for UI testing (lean MVP).

Generates realistic call/put prices using Black-Scholes for a grid of
strikes and expiries. Used when options_live_chain feature flag is off.
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.options.bs_calculator import BlackScholesCalculator

__version__ = "10.0.0"

__all__ = [
    "OptionContract",
    "MockOptionsChain",
]

_DEFAULT_STRIKES_PCT  = [0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20]
_DEFAULT_EXPIRIES_DAYS = [7, 14, 30, 60, 90]


@dataclass(frozen=True)
class OptionContract:
    ticker:       str
    option_type:  str       # "call" | "put"
    strike:       float
    expiry_days:  int
    t_years:      float
    spot:         float
    iv:           float
    price:        float
    delta:        float
    gamma:        float
    vega:         float
    theta:        float
    rho:          float
    is_itm:       bool


class MockOptionsChain:
    """Generate a synthetic option chain via Black-Scholes.

    Usage::

        chain = MockOptionsChain()
        contracts = chain.generate(ticker="SPY", spot=500.0, iv=0.18, r=0.05)
        # Returns list[OptionContract] across default strikes and expiries.
    """

    def __init__(self) -> None:
        self._calc = BlackScholesCalculator()

    def generate(
        self,
        ticker:       str,
        spot:         float,
        iv:           float,
        r:            float  = 0.05,
        q:            float  = 0.0,
        strikes_pct:  list[float] | None = None,
        expiry_days:  list[int]   | None = None,
    ) -> list[OptionContract]:
        """Generate mock option contracts for a ticker.

        Args:
            ticker:       Ticker symbol (label only, not fetched).
            spot:         Current spot price.
            iv:           Flat implied volatility to use across all strikes (simplified).
            r:            Risk-free rate.
            q:            Continuous dividend yield.
            strikes_pct:  Strike prices as fraction of spot. Defaults to ±20% grid.
            expiry_days:  List of days to expiry. Defaults to [7,14,30,60,90].

        Returns:
            Flat list of OptionContract for all (strike, expiry, type) combinations.
        """
        strikes_pct = strikes_pct or _DEFAULT_STRIKES_PCT
        expiry_days = expiry_days or _DEFAULT_EXPIRIES_DAYS

        contracts: list[OptionContract] = []
        for days in expiry_days:
            t = days / 365.0
            for pct in strikes_pct:
                K = round(spot * pct, 2)
                for opt_type in ("call", "put"):
                    result = self._calc.price(spot, K, t, r, iv, q, opt_type)
                    is_itm = (K < spot) if opt_type == "call" else (K > spot)
                    contracts.append(OptionContract(
                        ticker      = ticker,
                        option_type = opt_type,
                        strike      = K,
                        expiry_days = days,
                        t_years     = t,
                        spot        = spot,
                        iv          = iv,
                        price       = result.price,
                        delta       = result.greeks.delta,
                        gamma       = result.greeks.gamma,
                        vega        = result.greeks.vega,
                        theta       = result.greeks.theta,
                        rho         = result.greeks.rho,
                        is_itm      = is_itm,
                    ))
        return contracts

    def atm_contracts(
        self,
        ticker: str,
        spot:   float,
        iv:     float,
        r:      float = 0.05,
        q:      float = 0.0,
        expiry_days: list[int] | None = None,
    ) -> list[OptionContract]:
        """Return only ATM (spot == strike) call + put for each expiry."""
        return self.generate(
            ticker=ticker, spot=spot, iv=iv, r=r, q=q,
            strikes_pct=[1.00],
            expiry_days=expiry_days or _DEFAULT_EXPIRIES_DAYS,
        )
