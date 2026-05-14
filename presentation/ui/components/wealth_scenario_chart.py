"""Wealth scenario fan chart — Monte Carlo percentile bands."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from presentation.ui.theme import DesignTokens, hex_to_rgba

if TYPE_CHECKING:
    from personal.wealth_scenarios import WealthSimulationResult

__version__ = "6.0.0"

__all__ = ["build_wealth_fan_figure", "render_wealth_scenario_chart"]


def build_wealth_fan_figure(
    tokens: DesignTokens,
    result: WealthSimulationResult,
    title: str = "Wealth Projection — Monte Carlo Fan",
) -> Any:
    """Build a fan chart with P10/P50/P90 bands.

    The X-axis is monthly index; Y-axis is wealth (real or nominal terms
    depending on the simulation result).
    """
    import plotly.graph_objects as go

    months = np.arange(len(result.percentile_50))
    c = tokens.colors

    fig = go.Figure()
    # Optimistic upper band
    fig.add_trace(go.Scatter(
        x=months, y=result.percentile_90,
        line={"color": c.positive, "width": 1, "dash": "dot"},
        name="P90 (Optimistic)",
    ))
    # P10 lower band
    fig.add_trace(go.Scatter(
        x=months, y=result.percentile_10,
        line={"color": c.negative, "width": 1, "dash": "dot"},
        fill="tonexty", fillcolor=hex_to_rgba(c.accent_primary, 0.1),
        name="P10 (Pessimistic)",
    ))
    # Median (base case) on top of fill
    fig.add_trace(go.Scatter(
        x=months, y=result.percentile_50,
        line={"color": c.accent_primary, "width": 3},
        name="P50 (Base)",
    ))

    suffix = " (real terms)" if result.real_terms else " (nominal)"
    fig.update_layout(
        title=title + suffix,
        template=tokens.plotly.template,
        paper_bgcolor=tokens.plotly.paper_bgcolor,
        plot_bgcolor=tokens.plotly.plot_bgcolor,
        font={"family": tokens.plotly.font_family, "color": tokens.plotly.font_color},
        height=tokens.plotly.height_lg,
        hovermode="x unified",
        xaxis_title="Months",
        yaxis_title="Wealth",
    )
    return fig


def render_wealth_scenario_chart(
    tokens: DesignTokens,
    result: WealthSimulationResult,
    title: str = "Wealth Projection — Monte Carlo Fan",
) -> None:  # pragma: no cover
    """Render the Monte Carlo fan chart."""
    fig = build_wealth_fan_figure(tokens, result, title)
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso
    import streamlit as st  # pragma: no cover
    st.plotly_chart(fig, use_container_width=True)
