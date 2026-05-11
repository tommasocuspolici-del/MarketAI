"""Regime badge — visual indicator of HMM market regime (bull/bear/etc.)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "6.0.0"

__all__ = ["build_regime_html", "render_regime_badge"]


def build_regime_html(tokens: DesignTokens, regime: str) -> str:
    """Build HTML for a regime badge."""
    color = tokens.colors.for_regime(regime)
    icon = {"bull": "🐂", "bear": "🐻", "transition": "⚖️", "stress": "🚨"}.get(
        regime.lower(), "❓"
    )
    return (
        f'<div style="background-color: {color}33; color: {color}; '
        f"border: 2px solid {color}; border-radius: "
        f"{tokens.borders.radius_md}; padding: {tokens.spacing.unit_md}; "
        'text-align: center;">'
        f'<div style="font-size: {tokens.typography.font_size_2xl};">{icon}</div>'
        f'<div style="font-size: {tokens.typography.font_size_lg}; '
        f'font-weight: {tokens.typography.font_weight_bold};">'
        f"{regime.upper()}"
        "</div>"
        "</div>"
    )


def render_regime_badge(tokens: DesignTokens, regime: str) -> None:  # pragma: no cover
    """Render a market regime badge."""
    html = build_regime_html(tokens, regime)
    try:  # pragma: no cover
        import streamlit as st
        st.markdown(html, unsafe_allow_html=True)
    except ImportError:
        return  # pragma: no cover
