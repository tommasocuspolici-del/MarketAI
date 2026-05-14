"""Candlestick pro chart — OHLCV with configurable overlays (Plotly)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

    from presentation.ui.theme import DesignTokens

__version__ = "6.0.0"

__all__ = ["build_candlestick_figure", "render_candlestick_pro"]


def build_candlestick_figure(
    tokens: DesignTokens,
    ohlcv: pd.DataFrame,
    title: str,
    overlays: list[dict[str, Any]] | None = None,
) -> Any:
    """Build a Plotly figure with candlesticks + optional overlays.

    Args:
        ohlcv: DataFrame with ts, open, high, low, close, volume columns.
        overlays: Optional list of dicts, each with 'name' and 'series' keys.

    Returns:
        Plotly Figure object (typed Any to avoid hard plotly dep at module load).
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.7, 0.3],
        subplot_titles=(title, "Volume"),
    )
    c = tokens.colors

    fig.add_trace(
        go.Candlestick(
            x=ohlcv["ts"] if "ts" in ohlcv.columns else ohlcv.index,
            open=ohlcv["open"],
            high=ohlcv["high"],
            low=ohlcv["low"],
            close=ohlcv["close"],
            name="OHLC",
            increasing_line_color=c.positive,
            decreasing_line_color=c.negative,
        ),
        row=1, col=1,
    )

    fig.add_trace(
        go.Bar(
            x=ohlcv["ts"] if "ts" in ohlcv.columns else ohlcv.index,
            y=ohlcv["volume"],
            name="Volume",
            marker_color=c.accent_primary,
        ),
        row=2, col=1,
    )

    # Optional overlays (e.g. SMA, EMA, Bollinger Bands)
    for overlay in overlays or []:
        fig.add_trace(
            go.Scatter(
                x=ohlcv["ts"] if "ts" in ohlcv.columns else ohlcv.index,
                y=overlay["series"],
                name=overlay["name"],
                line={"width": 2},
            ),
            row=1, col=1,
        )

    fig.update_layout(
        template=tokens.plotly.template,
        paper_bgcolor=tokens.plotly.paper_bgcolor,
        plot_bgcolor=tokens.plotly.plot_bgcolor,
        font={"family": tokens.plotly.font_family, "color": tokens.plotly.font_color},
        height=tokens.plotly.height_lg,
        xaxis_rangeslider_visible=False,
    )
    return fig


def render_candlestick_pro(
    tokens: DesignTokens,
    ohlcv: pd.DataFrame,
    title: str,
    overlays: list[dict[str, Any]] | None = None,
) -> None:  # pragma: no cover
    """Render a candlestick chart with overlays."""
    fig = build_candlestick_figure(tokens, ohlcv, title, overlays)
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso
    import streamlit as st  # pragma: no cover
    st.plotly_chart(fig, use_container_width=True)
