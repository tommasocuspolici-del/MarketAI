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
    # BUGFIX v7.2.4: supporta sia dict (mock/test) sia oggetti NetWorthSnapshot
    def _get(snap, key, fallback_key=None):
        if isinstance(snap, dict):
            return snap.get(key) or (snap.get(fallback_key) if fallback_key else None)
        return getattr(snap, key, None)

    sorted_snaps = sorted(
        snapshots,
        key=lambda s: _get(s, "captured_at", "snapshot_date") or ""
    )
    timestamps = [_get(s, "captured_at", "snapshot_date") for s in sorted_snaps]
    assets = [_get(s, "total_assets") or 0.0 for s in sorted_snaps]
    liabs = [-(_get(s, "total_liabilities") or 0.0) for s in sorted_snaps]
    net = [_get(s, "net_worth") or 0.0 for s in sorted_snaps]

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
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso
    import streamlit as st  # pragma: no cover
    st.plotly_chart(fig, use_container_width=True)
