"""Backtest report — equity curve + drawdown + performance table."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from presentation.ui.theme import DesignTokens, hex_to_rgba

if TYPE_CHECKING:
    from engine.backtesting import BacktestResult

__version__ = "6.0.0"

__all__ = [
    "build_drawdown_figure",
    "build_equity_curve_figure",
    "build_metrics_table",
    "render_backtest_report",
]


def build_equity_curve_figure(
    tokens: DesignTokens,
    result: BacktestResult,
) -> Any:
    """Build the equity curve figure."""
    import plotly.graph_objects as go

    fig = go.Figure(
        go.Scatter(
            x=result.equity_curve.index,
            y=result.equity_curve.values,
            mode="lines",
            line={"color": tokens.colors.accent_primary, "width": 2},
            name="Equity",
        )
    )
    fig.update_layout(
        title=f"Equity Curve — {result.strategy_name} ({result.ticker})",
        template=tokens.plotly.template,
        paper_bgcolor=tokens.plotly.paper_bgcolor,
        plot_bgcolor=tokens.plotly.plot_bgcolor,
        font={"family": tokens.plotly.font_family, "color": tokens.plotly.font_color},
        height=tokens.plotly.height_md,
        yaxis_title="Equity",
    )
    return fig


def build_drawdown_figure(
    tokens: DesignTokens, result: BacktestResult
) -> Any:
    """Build the underwater drawdown figure (vectorized)."""
    import plotly.graph_objects as go

    eq = result.equity_curve.to_numpy()
    running_max = np.maximum.accumulate(eq)
    drawdown = eq / running_max - 1.0

    fig = go.Figure(
        go.Scatter(
            x=result.equity_curve.index,
            y=drawdown * 100,
            mode="lines",
            line={"color": tokens.colors.negative, "width": 1.5},
            fill="tozeroy",
            fillcolor=hex_to_rgba(tokens.colors.negative, 0.2),
            name="Drawdown %",
        )
    )
    fig.update_layout(
        title="Drawdown (%)",
        template=tokens.plotly.template,
        paper_bgcolor=tokens.plotly.paper_bgcolor,
        plot_bgcolor=tokens.plotly.plot_bgcolor,
        font={"family": tokens.plotly.font_family, "color": tokens.plotly.font_color},
        height=tokens.plotly.height_sm,
        yaxis_title="DD %",
    )
    return fig


def build_metrics_table(result: BacktestResult) -> pd.DataFrame:
    """Build a performance metrics table (DataFrame for st.dataframe)."""
    perf = result.performance
    return pd.DataFrame(
        [
            ("Total Return",       f"{perf.total_return:+.2%}"),
            ("Annualized Return",  f"{perf.annualized_return:+.2%}"),
            ("Annualized Vol",     f"{perf.annualized_vol:.2%}"),
            ("Sharpe Ratio",       f"{perf.sharpe_ratio:.2f}"),
            ("Sortino Ratio",      f"{perf.sortino_ratio:.2f}"),
            ("Max Drawdown",       f"{perf.max_drawdown:.2%}"),
            ("Calmar Ratio",       f"{perf.calmar_ratio:.2f}"),
            ("Win Rate",           f"{perf.win_rate:.2%}"),
            ("Profit Factor",      f"{perf.profit_factor:.2f}"),
            ("# Trades",           f"{result.n_trades}"),
            ("Total Fees",         f"{result.fees_total:.2f}"),
        ],
        columns=["Metric", "Value"],
    )


def render_backtest_report(
    tokens: DesignTokens, result: BacktestResult
) -> None:  # pragma: no cover
    """Render the full backtest report (charts + metrics table)."""
    try:  # pragma: no cover
        import streamlit as st
    except ImportError:
        return  # pragma: no cover

    st.plotly_chart(
        build_equity_curve_figure(tokens, result), use_container_width=True
    )
    st.plotly_chart(
        build_drawdown_figure(tokens, result), use_container_width=True
    )
    st.dataframe(build_metrics_table(result), use_container_width=True, hide_index=True)
