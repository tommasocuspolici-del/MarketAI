"""StrategyBuilder — P&L profiles for 4 option strategies (Lean MVP).

Strategies:
  straddle       — long call + long put at same ATM strike
  collar         — long stock + long put (protection) + short call (cap)
  covered_call   — long stock + short call (yield enhancement)
  vertical_spread — long call/put at K_long + short call/put at K_short

Each strategy returns a StrategyResult with cost, max_profit, max_loss,
breakeven points, and a P&L profile sampled across a spot-price range.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from engine.options.bs_calculator import BlackScholesCalculator

__version__ = "10.0.0"

__all__ = [
    "StrategyResult",
    "StrategyBuilder",
]

_PROFILE_POINTS = 100   # number of spot prices in P&L profile
_INF = float("inf")


@dataclass(frozen=True)
class StrategyResult:
    strategy_name:  str
    net_premium:    float              # positive = paid (debit), negative = received (credit)
    max_profit:     float              # +inf for uncapped upside
    max_loss:       float              # negative number; -inf for naked short
    breakevens:     list[float]
    pnl_profile:    list[tuple[float, float]]   # (spot_at_expiry, pnl)
    legs:           list[dict[str, object]]  # description of each leg


class StrategyBuilder:
    """Build P&L profiles for option strategies.

    Usage::

        builder = StrategyBuilder()
        result  = builder.straddle(S=100, K=100, T=0.25, r=0.05, sigma=0.20)
        print(result.net_premium, result.breakevens)
    """

    def __init__(self) -> None:
        self._calc = BlackScholesCalculator()

    # ── Public strategy methods ────────────────────────────────────────────

    def straddle(
        self,
        S:     float,
        K:     float,
        T:     float,
        r:     float,
        sigma: float,
        q:     float = 0.0,
    ) -> StrategyResult:
        """Long straddle: buy call + buy put at same strike K (ATM)."""
        call = self._calc.price(S, K, T, r, sigma, q, "call")
        put  = self._calc.price(S, K, T, r, sigma, q, "put")
        net_premium = call.price + put.price   # debit

        def pnl(spot: float) -> float:
            call_payoff = max(spot - K, 0.0)
            put_payoff  = max(K - spot, 0.0)
            return call_payoff + put_payoff - net_premium

        profile = self._profile(S, pnl)
        return StrategyResult(
            strategy_name = "straddle",
            net_premium   = net_premium,
            max_profit    = _INF,
            max_loss      = -net_premium,
            breakevens    = [K - net_premium, K + net_premium],
            pnl_profile   = profile,
            legs          = [
                {"type": "long_call", "K": K, "premium": call.price},
                {"type": "long_put",  "K": K, "premium": put.price},
            ],
        )

    def collar(
        self,
        S:       float,
        K_put:   float,     # put strike (protection floor), K_put < S
        K_call:  float,     # call strike (cap), K_call > S
        T:       float,
        r:       float,
        sigma:   float,
        q:       float = 0.0,
        shares:  int   = 100,
    ) -> StrategyResult:
        """Collar: long stock + long put (floor) + short call (cap).

        Net premium is typically close to zero (zero-cost collar).
        """
        put  = self._calc.price(S, K_put,  T, r, sigma, q, "put")
        call = self._calc.price(S, K_call, T, r, sigma, q, "call")
        net_premium = put.price - call.price   # put buy - call sell

        def pnl(spot: float) -> float:
            stock_pnl   = (spot - S) * shares
            put_payoff  = (max(K_put - spot, 0.0) - put.price) * shares
            call_payoff = (call.price - max(spot - K_call, 0.0)) * shares
            return stock_pnl + put_payoff + call_payoff

        profile = self._profile(S, pnl)

        # Scaled by shares: (K_put - S - net_premium) * shares
        max_loss   = (K_put  - S - net_premium) * shares
        max_profit = (K_call - S - net_premium) * shares

        # Breakeven per-share: S + net_premium
        be = S + net_premium

        return StrategyResult(
            strategy_name = "collar",
            net_premium   = net_premium,
            max_profit    = max_profit,
            max_loss      = max_loss,
            breakevens    = [be],
            pnl_profile   = profile,
            legs          = [
                {"type": "long_stock", "S": S, "shares": shares},
                {"type": "long_put",   "K": K_put,  "premium": put.price},
                {"type": "short_call", "K": K_call, "premium": call.price},
            ],
        )

    def covered_call(
        self,
        S:     float,
        K:     float,      # call strike, K > S (OTM call)
        T:     float,
        r:     float,
        sigma: float,
        q:     float = 0.0,
        shares: int  = 100,
    ) -> StrategyResult:
        """Covered call: long stock + short OTM call (yield enhancement)."""
        call = self._calc.price(S, K, T, r, sigma, q, "call")
        net_premium = -call.price   # credit received

        def pnl(spot: float) -> float:
            stock_pnl   = (spot - S) * shares
            call_payoff = (call.price - max(spot - K, 0.0)) * shares
            return stock_pnl + call_payoff

        profile = self._profile(S, pnl)

        max_profit = (K - S + call.price) * shares
        max_loss   = (-S + call.price) * shares    # stock drops to 0
        be         = S - call.price                # per-share breakeven

        return StrategyResult(
            strategy_name = "covered_call",
            net_premium   = net_premium,
            max_profit    = max_profit,
            max_loss      = max_loss,
            breakevens    = [be],
            pnl_profile   = profile,
            legs          = [
                {"type": "long_stock",  "S": S, "shares": shares},
                {"type": "short_call",  "K": K, "premium": call.price},
            ],
        )

    def vertical_spread(
        self,
        S:           float,
        K_long:      float,    # long leg strike
        K_short:     float,    # short leg strike
        T:           float,
        r:           float,
        sigma:       float,
        q:           float = 0.0,
        option_type: str   = "call",
    ) -> StrategyResult:
        """Vertical spread: long K_long + short K_short (same type, same expiry).

        Call spread (bull): K_long < K_short — debit, capped upside.
        Put spread  (bear): K_long > K_short — debit, capped downside profit.
        """
        long_leg  = self._calc.price(S, K_long,  T, r, sigma, q, option_type)
        short_leg = self._calc.price(S, K_short, T, r, sigma, q, option_type)
        net_premium = long_leg.price - short_leg.price   # net debit (usually)

        if option_type == "call":
            # Bull call spread
            def pnl(spot: float) -> float:
                return (max(spot - K_long, 0.0) - max(spot - K_short, 0.0)
                        - net_premium)

            max_profit = abs(K_short - K_long) - net_premium
            max_loss   = -net_premium
            be         = K_long + net_premium
        else:
            # Bear put spread
            def pnl(spot: float) -> float:
                return (max(K_long - spot, 0.0) - max(K_short - spot, 0.0)
                        - net_premium)

            max_profit = abs(K_long - K_short) - net_premium
            max_loss   = -net_premium
            be         = K_long - net_premium

        profile = self._profile(S, pnl)

        return StrategyResult(
            strategy_name = f"vertical_{option_type}_spread",
            net_premium   = net_premium,
            max_profit    = max_profit,
            max_loss      = max_loss,
            breakevens    = [be],
            pnl_profile   = profile,
            legs          = [
                {"type": f"long_{option_type}",  "K": K_long,  "premium": long_leg.price},
                {"type": f"short_{option_type}", "K": K_short, "premium": short_leg.price},
            ],
        )

    # ── Internal ───────────────────────────────────────────────────────────

    @staticmethod
    def _profile(
        S: float,
        pnl_fn: Callable[[float], float],
        n: int = _PROFILE_POINTS,
    ) -> list[tuple[float, float]]:
        """Sample P&L across spot range [S*0.5, S*1.5]."""
        lo, hi = S * 0.5, S * 1.5
        step   = (hi - lo) / (n - 1)
        return [(lo + i * step, pnl_fn(lo + i * step)) for i in range(n)]
