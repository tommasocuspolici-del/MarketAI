"""Performance metrics for backtest results.

All metrics computed vectorized via numpy/scipy (Rule 8). The report is
a frozen dataclass so it can be safely passed to UI/persistence.

Standard finance conventions:
  · annualization factor = 252 trading days per year
  · risk-free rate default = 0 (use real one for Sharpe in production)
  · returns: log-returns of equity curve
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pandas as pd

__version__ = "6.0.0"

__all__ = ["PerformanceReport", "compute_performance_report"]

_TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True, slots=True)
class PerformanceReport:
    """Complete performance summary of a backtest.

    All metrics derived from a single equity curve. Produced by
    ``compute_performance_report()``.
    """

    total_return: float           # (final / initial) - 1
    annualized_return: float      # CAGR
    annualized_vol: float          # std of returns * sqrt(252)
    sharpe_ratio: float            # (ann_ret - rf) / ann_vol
    sortino_ratio: float           # (ann_ret - rf) / downside_vol
    max_drawdown: float            # max peak-to-trough loss (negative number)
    calmar_ratio: float            # ann_ret / |max_drawdown|
    win_rate: float                # fraction of positive return days
    profit_factor: float           # sum(gains) / |sum(losses)|
    n_periods: int                 # number of bars in the equity curve

    def to_dict(self) -> dict[str, float | int]:
        """Plain dict for logging / persistence."""
        return asdict(self)


def compute_performance_report(
    equity: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = _TRADING_DAYS_PER_YEAR,
) -> PerformanceReport:
    """Compute all standard backtest metrics from an equity curve.

    Args:
        equity: Equity curve (NAV over time). Must have at least 2 points.
        risk_free_rate: Annualized risk-free rate (e.g. 0.02 for 2%).
        periods_per_year: Annualization factor (252 for daily, 12 monthly).

    Returns:
        PerformanceReport with all metrics. Edge cases (constant equity,
        zero volatility) return well-defined sentinel values.
    """
    if len(equity) < 2:
        return _empty_report()

    eq = equity.astype("float64").to_numpy()

    # ─── Returns ─────────────────────────────────────────────────────────
    # Log-returns: più stabili e additivi rispetto ai semplici
    log_returns = np.diff(np.log(np.maximum(eq, 1e-12)))
    n_periods = len(log_returns)

    # Total return da inizio a fine
    total_return = float(eq[-1] / eq[0] - 1.0)

    # CAGR: (1 + total_return)^(periods_per_year/n) - 1
    if n_periods > 0:
        years = n_periods / periods_per_year
        annualized_return = float((1.0 + total_return) ** (1.0 / max(years, 1e-9)) - 1.0)
    else:
        annualized_return = 0.0

    # ─── Volatility ──────────────────────────────────────────────────────
    annualized_vol = float(np.std(log_returns, ddof=1) * np.sqrt(periods_per_year)) \
        if n_periods > 1 else 0.0

    # ─── Sharpe ─────────────────────────────────────────────────────────
    if annualized_vol > 0:
        sharpe_ratio = float((annualized_return - risk_free_rate) / annualized_vol)
    else:
        sharpe_ratio = 0.0

    # ─── Sortino (downside deviation only) ──────────────────────────────
    downside = log_returns[log_returns < 0.0]
    if len(downside) > 1:
        downside_vol = float(np.std(downside, ddof=1) * np.sqrt(periods_per_year))
        sortino_ratio = (
            float((annualized_return - risk_free_rate) / downside_vol)
            if downside_vol > 0 else 0.0
        )
    else:
        sortino_ratio = 0.0

    # ─── Max Drawdown (peak-to-trough) ──────────────────────────────────
    running_max = np.maximum.accumulate(eq)
    drawdowns = eq / running_max - 1.0
    max_drawdown = float(drawdowns.min())  # negativo

    # ─── Calmar ratio ───────────────────────────────────────────────────
    calmar_ratio = (
        float(annualized_return / abs(max_drawdown)) if max_drawdown < 0 else 0.0
    )

    # ─── Win rate ───────────────────────────────────────────────────────
    win_rate = float((log_returns > 0.0).sum() / n_periods) if n_periods > 0 else 0.0

    # ─── Profit factor ──────────────────────────────────────────────────
    gains = log_returns[log_returns > 0.0].sum()
    losses_abs = -log_returns[log_returns < 0.0].sum()
    profit_factor = float(gains / losses_abs) if losses_abs > 0 else 0.0

    return PerformanceReport(
        total_return=total_return,
        annualized_return=annualized_return,
        annualized_vol=annualized_vol,
        sharpe_ratio=sharpe_ratio,
        sortino_ratio=sortino_ratio,
        max_drawdown=max_drawdown,
        calmar_ratio=calmar_ratio,
        win_rate=win_rate,
        profit_factor=profit_factor,
        n_periods=int(n_periods + 1),  # bars (not returns)
    )


def _empty_report() -> PerformanceReport:
    """Sentinel report for empty/single-point equity curves."""
    return PerformanceReport(
        total_return=0.0,
        annualized_return=0.0,
        annualized_vol=0.0,
        sharpe_ratio=0.0,
        sortino_ratio=0.0,
        max_drawdown=0.0,
        calmar_ratio=0.0,
        win_rate=0.0,
        profit_factor=0.0,
        n_periods=0,
    )
