"""Health status bar component — shows system health on every page."""
from __future__ import annotations

from typing import TYPE_CHECKING

from shared.types import HealthState

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens
    from shared.health import SystemHealth

__version__ = "6.0.0"

__all__ = ["build_health_html", "render_health_status_bar"]


def build_health_html(tokens: DesignTokens, health: SystemHealth) -> str:
    """Build HTML for the health bar (testable)."""
    c = tokens.colors
    state_color = {
        HealthState.OPERATIONAL: c.health_operational,
        HealthState.DEGRADED: c.health_degraded,
        HealthState.DOWN: c.health_down,
    }.get(health.status, c.neutral)

    icon = {
        HealthState.OPERATIONAL: "🟢",
        HealthState.DEGRADED: "🟡",
        HealthState.DOWN: "🔴",
    }.get(health.status, "⚪")

    n_components = len(health.components)
    return (
        f'<div class="market-ai-health-bar" '
        f'style="background-color: {state_color}33; '
        f'border: 1px solid {state_color}; color: {c.text_primary};">'
        f"{icon} <strong>System: {health.status.value.upper()}</strong> "
        f"({n_components} components)"
        "</div>"
    )


def render_health_status_bar(
    tokens: DesignTokens, health: SystemHealth
) -> None:  # pragma: no cover
    """Render the health status bar in the sidebar (Rule 30)."""
    html = build_health_html(tokens, health)

    try:  # pragma: no cover
        import streamlit as st
        st.sidebar.markdown(html, unsafe_allow_html=True)
        # Expandable detail per component
        with st.sidebar.expander("Component details"):
            for comp in health.components:
                st.sidebar.markdown(
                    f"**{comp.name}**: `{comp.status.value}` "
                    f"({comp.latency_ms or 0:.0f}ms)"
                )
                if comp.message:
                    st.sidebar.caption(comp.message)
    except ImportError:
        return  # pragma: no cover
