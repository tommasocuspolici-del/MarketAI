"""CollarAdvisor — suggest collar protection when portfolio_beta > threshold.

Pure logic: no Streamlit, fully testable.
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.options.strategy_builder import StrategyBuilder, StrategyResult

__version__ = "10.0.0"

__all__ = [
    "CollarSuggestion",
    "CollarAdvisor",
]

_DEFAULT_BETA_THRESHOLD: float = 1.3
_DEFAULT_PUT_OFFSET:     float = 0.05   # 5% OTM put (floor at S*0.95)
_DEFAULT_CALL_OFFSET:    float = 0.05   # 5% OTM call (cap at S*1.05)


@dataclass(frozen=True)
class CollarSuggestion:
    suggested:       bool
    portfolio_beta:  float
    beta_threshold:  float
    reason:          str
    strategy:        StrategyResult | None   # None when suggested=False
    spot:            float
    k_put:           float
    k_call:          float


class CollarAdvisor:
    """Recommend a collar hedge when portfolio beta exceeds a threshold.

    Usage::

        advisor    = CollarAdvisor()
        suggestion = advisor.evaluate(portfolio_beta=1.45, spot=500.0,
                                       iv=0.18, t_years=0.25)
        if suggestion.suggested:
            print(f"Collar: {suggestion.reason}")
            print(f"Net premium: {suggestion.strategy.net_premium:.2f}")
    """

    def __init__(
        self,
        beta_threshold: float = _DEFAULT_BETA_THRESHOLD,
        put_offset:     float = _DEFAULT_PUT_OFFSET,
        call_offset:    float = _DEFAULT_CALL_OFFSET,
    ) -> None:
        self._beta_threshold = beta_threshold
        self._put_offset     = put_offset
        self._call_offset    = call_offset
        self._builder        = StrategyBuilder()

    def evaluate(
        self,
        portfolio_beta: float,
        spot:           float,
        iv:             float,
        t_years:        float,
        r:              float = 0.05,
        q:              float = 0.0,
    ) -> CollarSuggestion:
        """Evaluate whether a collar hedge is recommended.

        Args:
            portfolio_beta: Current portfolio beta vs benchmark.
            spot:           Reference ETF price (e.g. SPY or benchmark).
            iv:             Implied volatility of the benchmark.
            t_years:        Hedge horizon in years.
            r:              Risk-free rate.
            q:              Dividend yield.

        Returns:
            CollarSuggestion with suggested=True and a StrategyResult when
            portfolio_beta > beta_threshold.
        """
        if portfolio_beta <= self._beta_threshold:
            return CollarSuggestion(
                suggested       = False,
                portfolio_beta  = portfolio_beta,
                beta_threshold  = self._beta_threshold,
                reason          = (
                    f"Beta {portfolio_beta:.2f} ≤ {self._beta_threshold:.1f}: "
                    f"no hedge required."
                ),
                strategy        = None,
                spot            = spot,
                k_put           = spot * (1.0 - self._put_offset),
                k_call          = spot * (1.0 + self._call_offset),
            )

        k_put  = round(spot * (1.0 - self._put_offset), 2)
        k_call = round(spot * (1.0 + self._call_offset), 2)

        strategy = self._builder.collar(
            S=spot, K_put=k_put, K_call=k_call,
            T=t_years, r=r, sigma=iv, q=q,
        )

        return CollarSuggestion(
            suggested       = True,
            portfolio_beta  = portfolio_beta,
            beta_threshold  = self._beta_threshold,
            reason          = (
                f"Portfolio beta {portfolio_beta:.2f} > {self._beta_threshold:.1f}: "
                f"collar protection recommended. "
                f"Floor: {k_put:.0f} | Cap: {k_call:.0f} | "
                f"Net premium: {strategy.net_premium:+.2f}"
            ),
            strategy        = strategy,
            spot            = spot,
            k_put           = k_put,
            k_call          = k_call,
        )
