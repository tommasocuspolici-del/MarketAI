"""Net worth timeline — area chart of historical wealth_snapshots."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from presentation.ui.theme import DesignTokens, hex_to_rgba

if TYPE_CHECKING:
    from personal.networth import NetWorthSnapshot

__version__ = "6.0.0"

__all__ = ["build_net_worth_figure", "render_net_worth_chart"]


def build_net_worth_figure(
    tokens: DesignTokens,
    snapshots: list[NetWorthSnapshot],
    title: str = "Net Worth Over Time",
) -> Any:
    """Build a Plotly area chart showing assets, liabilities, and net worth."""
    import plotly.graph_objects as go

    fig = go.Figure()
    if not snapshots:
        fig.update_layout(title=f"{title} (no data)")
        return fig

    # Sort by date asc for proper timeline
    sorted_snaps = sorted(snapshots, key=lambda s: s.captured_at)
    timestamps = [s.captured_at for s in sorted_snaps]
    assets = [s.total_assets for s in sorted_snaps]
    liabs = [-s.total_liabilities for s in sorted_snaps]   # negative for waterfall feel
    net = [s.net_worth for s in sorted_snaps]

    c = tokens.colors

    fig.add_trace(go.Scatter(
        x=timestamps, y=assets, name="Assets",
        line={"color": c.positive, "width": 2},
        fill="tozeroy", fillcolor=hex_to_rgba(c.positive, 0.2),
    ))
    fig.add_trace(go.Scatter(
        x=timestamps, y=liabs, name="Liabilities",
        line={"color": c.negative, "width": 2},
        fill="tozeroy", fillcolor=hex_to_rgba(c.negative, 0.2),
    ))
    fig.add_trace(go.Scatter(
        x=timestamps, y=net, name="Net Worth",
        line={"color": c.accent_primary, "width": 3, "dash": "solid"},
    ))

    fig.update_layout(
        title=title,
        template=tokens.plotly.template,
        paper_bgcolor=tokens.plotly.paper_bgcolor,
        plot_bgcolor=tokens.plotly.plot_bgcolor,
        font={"family": tokens.plotly.font_family, "color": tokens.plotly.font_color},
        height=tokens.plotly.height_md,
        hovermode="x unified",
        yaxis_title="Amount",
        xaxis_title="Date",
    )
    return fig


def render_net_worth_chart(
    tokens: DesignTokens,
    snapshots: list[NetWorthSnapshot],
    title: str = "Net Worth Over Time",
) -> None:  # pragma: no cover
    """Render the net worth timeline."""
    fig = build_net_worth_figure(tokens, snapshots, title)
    try:  # pragma: no cover
        import streamlit as st
        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        return  # pragma: no cover
