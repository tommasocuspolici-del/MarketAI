"""PersonalRiskBudget — VaR portfolio vs risk tolerance profile (#1).

Output: [-1, 1]
  > 0 → within risk budget (positive: room to add risk)
  < 0 → over budget (negative: reduce risk)
  0   → at limit
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from shared.signal_bus import get_signal_bus
from shared.signal_types import SIGNAL_CUSTOM_PREFIX, Signal

__version__ = "10.0.0"

__all__ = ["PersonalRiskBudgetIndicator", "RiskBudgetResult"]

_MAX_VAR_PCT_DEFAULT   = 0.15    # loaded from custom_indicators.yaml
_LOOKBACK_DAYS_DEFAULT = 252


@dataclass
class RiskBudgetResult:
    portfolio_var_pct:  float    # Estimated VaR as % of portfolio
    max_var_pct:        float    # Allowed maximum VaR
    budget_used:        float    # [0, 1]: how much of budget is consumed
    signal_value:       float    # [-1, 1]: positive = room, negative = over budget


class PersonalRiskBudgetIndicator:
    """Pre-built #1 — Portfolio VaR vs risk tolerance.

    Args:
        max_var_pct:   Maximum acceptable VaR as fraction (default 0.15 = 15%)
        lookback_days: Historical window for VaR estimation (default 252)
    """

    def __init__(
        self,
        max_var_pct:   float = _MAX_VAR_PCT_DEFAULT,
        lookback_days: int   = _LOOKBACK_DAYS_DEFAULT,
    ) -> None:
        self._max_var    = max_var_pct
        self._lookback   = lookback_days

    def compute(self, portfolio_returns: list[float] | None = None) -> RiskBudgetResult:
        """Compute risk budget signal.

        Args:
            portfolio_returns: Historical daily returns of the portfolio.
                               If None or empty, returns neutral signal (0.0).
        """
        if not portfolio_returns:
            return RiskBudgetResult(
                portfolio_var_pct = 0.0,
                max_var_pct       = self._max_var,
                budget_used       = 0.0,
                signal_value      = 0.0,
            )

        returns = np.array(portfolio_returns[-self._lookback:], dtype=np.float64)
        var_95  = float(np.percentile(returns, 5))   # 5th percentile → negative = loss
        var_pct = abs(var_95)

        budget_used  = float(np.clip(var_pct / self._max_var, 0.0, 2.0))
        signal_value = float(np.clip(1.0 - budget_used, -1.0, 1.0))

        return RiskBudgetResult(
            portfolio_var_pct = round(var_pct, 4),
            max_var_pct       = self._max_var,
            budget_used       = round(budget_used, 4),
            signal_value      = round(signal_value, 4),
        )

    def to_signal(self, result: RiskBudgetResult) -> Signal:
        return Signal(
            name          = f"{SIGNAL_CUSTOM_PREFIX}personal_risk_budget",
            value         = result.signal_value,
            confidence    = float(np.clip(1.0 - abs(result.signal_value - 0.0) / 2.0, 0.0, 1.0)),
            source_module = __name__,
            metadata      = {
                "var_pct":    result.portfolio_var_pct,
                "max_var":    result.max_var_pct,
                "budget_used": result.budget_used,
            },
        )
