"""Correlation network graph — NetworkX + Plotly visualization."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    import pandas as pd

    from presentation.ui.theme import DesignTokens

__version__ = "6.0.0"

__all__ = ["build_correlation_network_figure", "render_correlation_network"]


def build_correlation_network_figure(
    tokens: DesignTokens,
    correlation_matrix: pd.DataFrame,
    threshold: float = 0.5,
    title: str = "Asset Correlation Network",
) -> Any:
    """Build a network graph where nodes are assets and edges are
    correlations above ``threshold`` (absolute value).

    Args:
        correlation_matrix: Square symmetric DataFrame with asset names
            on both axes and Pearson correlations as values.
        threshold: Minimum |correlation| to draw an edge (default 0.5).
    """
    import plotly.graph_objects as go

    assets = list(correlation_matrix.columns)
    n = len(assets)
    if n < 2:
        # fallback: empty figure
        return go.Figure()

    # Posizioni circolari (deterministiche, no networkx layout call)
    angles = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    positions = {
        asset: (float(np.cos(angle)), float(np.sin(angle)))
        for asset, angle in zip(assets, angles, strict=True)
    }

    # Edge traces — None acts as a segment separator in Plotly line traces
    edge_x: list[float | None] = []
    edge_y: list[float | None] = []
    edge_colors: list[str] = []
    for i, a in enumerate(assets):
        for b in assets[i + 1:]:
            corr = float(correlation_matrix.loc[a, b])
            if abs(corr) >= threshold:
                x0, y0 = positions[a]
                x1, y1 = positions[b]
                edge_x.extend([x0, x1, None])
                edge_y.extend([y0, y1, None])
                # Verde per correlazione positiva, rosso per negativa
                color = (
                    tokens.colors.positive if corr > 0 else tokens.colors.negative
                )
                edge_colors.append(color)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=edge_x, y=edge_y,
            mode="lines",
            line={"width": 1.5, "color": tokens.colors.text_muted},
            hoverinfo="skip",
            showlegend=False,
        )
    )

    # Node trace
    node_x = [positions[a][0] for a in assets]
    node_y = [positions[a][1] for a in assets]
    fig.add_trace(
        go.Scatter(
            x=node_x, y=node_y,
            mode="markers+text",
            text=assets,
            textposition="top center",
            marker={
                "size": 30,
                "color": tokens.colors.accent_primary,
                "line": {"width": 2, "color": tokens.colors.text_primary},
            },
            hoverinfo="text",
            showlegend=False,
        )
    )

    fig.update_layout(
        title=title,
        template=tokens.plotly.template,
        paper_bgcolor=tokens.plotly.paper_bgcolor,
        plot_bgcolor=tokens.plotly.plot_bgcolor,
        font={"family": tokens.plotly.font_family, "color": tokens.plotly.font_color},
        height=tokens.plotly.height_lg,
        xaxis={"showgrid": False, "zeroline": False, "showticklabels": False},
        yaxis={"showgrid": False, "zeroline": False, "showticklabels": False},
    )
    return fig


def render_correlation_network(
    tokens: DesignTokens,
    correlation_matrix: pd.DataFrame,
    threshold: float = 0.5,
    title: str = "Asset Correlation Network",
) -> None:  # pragma: no cover
    """Render correlation network in Streamlit."""
    fig = build_correlation_network_figure(
        tokens, correlation_matrix, threshold, title
    )
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso
    import streamlit as st  # pragma: no cover
    st.plotly_chart(fig, use_container_width=True)
