"""Latency indicator — shows freshness/latency of real-time data (Rule 25)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from shared.types import now_utc

if TYPE_CHECKING:
    from datetime import datetime

    from presentation.ui.theme import DesignTokens

__version__ = "6.0.0"

__all__ = ["build_latency_html", "render_latency_indicator"]


def _get_color(tokens: DesignTokens, age_seconds: float) -> str:
    """Pick color based on data age (Rule 25: ≤60s for real-time)."""
    c = tokens.colors
    if age_seconds <= 60:
        return c.positive
    if age_seconds <= 300:   # 5 min
        return c.warning
    return c.negative


def build_latency_html(
    tokens: DesignTokens, source: str, last_update: datetime
) -> str:
    """Build HTML for latency indicator."""
    now = now_utc()
    last_update_utc = last_update if last_update.tzinfo else last_update.replace(tzinfo=now.tzinfo)
    age_seconds = max((now - last_update_utc).total_seconds(), 0.0)
    color = _get_color(tokens, age_seconds)

    if age_seconds < 60:
        label = f"{int(age_seconds)}s ago"
    elif age_seconds < 3600:
        label = f"{int(age_seconds / 60)}m ago"
    else:
        label = f"{int(age_seconds / 3600)}h ago"

    return (
        f'<span style="color: {color}; font-size: '
        f'{tokens.typography.font_size_xs};">'
        f"● {source}: {label}"
        "</span>"
    )


def render_latency_indicator(
    tokens: DesignTokens, source: str, last_update: datetime
) -> None:  # pragma: no cover
    """Render a latency indicator for a data source."""
    html = build_latency_html(tokens, source, last_update)
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso
    import streamlit as st  # pragma: no cover
    st.markdown(html, unsafe_allow_html=True)
