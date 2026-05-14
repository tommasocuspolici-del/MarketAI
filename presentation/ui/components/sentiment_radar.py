"""Sentiment radar — multi-source sentiment as polar/radar chart."""
from __future__ import annotations

from typing import Any

from presentation.ui.theme import DesignTokens, hex_to_rgba

__version__ = "6.0.0"

__all__ = ["build_sentiment_radar_figure", "render_sentiment_radar"]


def build_sentiment_radar_figure(
    tokens: DesignTokens,
    scores: dict[str, float],
    title: str = "Sentiment Composite",
) -> Any:
    """Build a radar/polar chart of sentiment scores per source.

    Args:
        scores: Mapping {source_name: score in [-1, 1]}.
        title: Chart title.
    """
    import plotly.graph_objects as go

    sources = list(scores.keys())
    # Normalizziamo a [0, 100] per leggibilità sul radar
    values_normalized = [(scores[s] + 1) * 50 for s in sources]

    # Determina il colore: verde se score medio > 0, rosso altrimenti
    avg = sum(scores.values()) / len(scores) if scores else 0.0
    line_color = tokens.colors.positive if avg > 0 else tokens.colors.negative

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=[*values_normalized, values_normalized[0]],   # close the polygon
            theta=[*sources, sources[0]],
            fill="toself",
            name="Sentiment",
            line={"color": line_color, "width": 2},
            fillcolor=hex_to_rgba(line_color, 0.2),
        )
    )
    fig.update_layout(
        title=title,
        template=tokens.plotly.template,
        paper_bgcolor=tokens.plotly.paper_bgcolor,
        font={"family": tokens.plotly.font_family, "color": tokens.plotly.font_color},
        polar={
            "radialaxis": {"visible": True, "range": [0, 100]},
            "bgcolor": tokens.plotly.plot_bgcolor,
        },
        height=tokens.plotly.height_md,
        showlegend=False,
    )
    return fig


def render_sentiment_radar(
    tokens: DesignTokens, scores: dict[str, float], title: str = "Sentiment Composite"
) -> None:  # pragma: no cover
    """Render the sentiment radar."""
    fig = build_sentiment_radar_figure(tokens, scores, title)
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso
    import streamlit as st  # pragma: no cover
    st.plotly_chart(fig, use_container_width=True)
