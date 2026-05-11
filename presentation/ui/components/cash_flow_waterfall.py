"""Cash flow waterfall — Plotly waterfall chart for monthly income/expense."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "6.0.0"

__all__ = ["build_waterfall_figure", "render_cash_flow_waterfall"]


def build_waterfall_figure(
    tokens: DesignTokens,
    categories: list[str],
    amounts: list[float],
    title: str = "Cash Flow Waterfall",
) -> Any:
    """Build a Plotly waterfall figure.

    Args:
        categories: e.g. ["Salary", "Bonus", "Rent", "Food", "Net"]
        amounts:    signed amounts (positive=income, negative=expense, last=net total)
    """
    import plotly.graph_objects as go

    if len(categories) != len(amounts):
        raise ValueError("categories and amounts must have same length")

    # Measure: "relative" for items, "total" for the last one (net)
    measures = ["relative"] * (len(categories) - 1) + ["total"]
    c = tokens.colors

    fig = go.Figure(
        go.Waterfall(
            measure=measures,
            x=categories,
            y=amounts,
            connector={"line": {"color": c.text_muted}},
            increasing={"marker": {"color": c.positive}},
            decreasing={"marker": {"color": c.negative}},
            totals={"marker": {"color": c.accent_primary}},
        )
    )
    fig.update_layout(
        title=title,
        template=tokens.plotly.template,
        paper_bgcolor=tokens.plotly.paper_bgcolor,
        plot_bgcolor=tokens.plotly.plot_bgcolor,
        font={"family": tokens.plotly.font_family, "color": tokens.plotly.font_color},
        height=tokens.plotly.height_md,
        showlegend=False,
        yaxis_title="Amount",
    )
    return fig


def render_cash_flow_waterfall(
    tokens: DesignTokens,
    categories: list[str],
    amounts: list[float],
    title: str = "Cash Flow Waterfall",
) -> None:  # pragma: no cover
    """Render a cash flow waterfall."""
    fig = build_waterfall_figure(tokens, categories, amounts, title)
    try:  # pragma: no cover
        import streamlit as st
        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        return  # pragma: no cover
