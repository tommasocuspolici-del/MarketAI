"""Page rendering helpers shared between dashboards.

Every dashboard page calls ``render_page(...)`` with its identifier; the
function sets up the page (auth + theme), renders the sidebar status,
and dispatches to a page-specific body function.

This file exists so that pages remain thin scripts (each ~30-50 lines)
while complex orchestration logic lives here, fully testable.
"""
from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from presentation.ui.layout import setup_page
from shared.types import HealthState, now_utc

if TYPE_CHECKING:
    from collections.abc import Callable

    from presentation.ui.theme import DesignTokens

__version__ = "6.0.0"

__all__ = [
    "build_mock_health",
    "build_mock_market_kpis",
    "render_page",
    "render_sidebar_status",
]


# ═══════════════════════════════════════════════════════════════════════════
# Mock data providers (fixture-friendly; pages will be wired to real data
# via bridge in Phase 8)
# ═══════════════════════════════════════════════════════════════════════════
def build_mock_health() -> Any:
    """Return a SystemHealth-like object for sidebar rendering."""
    from shared.health import ComponentHealth, SystemHealth
    components = [
        ComponentHealth(name="duckdb", status=HealthState.OPERATIONAL, latency_ms=8.0),
        ComponentHealth(name="sqlite", status=HealthState.OPERATIONAL, latency_ms=2.0),
        ComponentHealth(name="cache", status=HealthState.OPERATIONAL, latency_ms=0.5),
        ComponentHealth(name="scheduler", status=HealthState.OPERATIONAL),
    ]
    return SystemHealth(
        status=HealthState.OPERATIONAL,
        components=components,
        checked_at=now_utc(),
    )


def build_mock_market_kpis() -> list[dict[str, object]]:
    """Mock KPI bar data for E1_Market_Overview."""
    return [
        {"label": "S&P 500",  "value": 5_840.2, "delta": 0.0125, "fmt": "number_decimal"},
        {"label": "NASDAQ",   "value": 18_435.0, "delta": 0.0182, "fmt": "number_decimal"},
        {"label": "BTC/USD",  "value": 67_200.0, "delta": -0.013, "fmt": "currency_usd"},
        {"label": "EUR/USD",  "value": 1.085, "delta": 0.0021, "fmt": "number_decimal"},
        {"label": "Gold",     "value": 2_650.5, "delta": 0.0042, "fmt": "currency_usd"},
        {"label": "WTI Oil",  "value": 71.20, "delta": -0.0085, "fmt": "currency_usd"},
        {"label": "VIX",      "value": 16.5, "delta": -0.04, "fmt": "number_decimal"},
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Page rendering scaffolding
# ═══════════════════════════════════════════════════════════════════════════
def render_sidebar_status(tokens: DesignTokens) -> None:  # pragma: no cover
    """Render health bar + last-update timestamp in the sidebar.

    All dashboard pages call this immediately after setup_page().
    """
    from presentation.ui.components.health_status_bar import render_health_status_bar
    from presentation.ui.components.latency_indicator import render_latency_indicator

    health = build_mock_health()
    render_health_status_bar(tokens, health)

    last_update = now_utc() - timedelta(seconds=42)
    try:  # pragma: no cover
        import streamlit as st
        with st.sidebar:
            render_latency_indicator(tokens, "Market Data", last_update)
    except ImportError:
        return  # pragma: no cover


def render_page(
    title: str,
    icon: str,
    body_fn: Callable[[DesignTokens], None],
    require_auth_gate: bool = True,
) -> None:  # pragma: no cover
    """Standard page wrapper.

    1. setup_page (theme + CSS + auth)
    2. sidebar status (health + latency)
    3. body_fn — page-specific content
    """
    tokens = setup_page(title=title, icon=icon, require_auth_gate=require_auth_gate)
    render_sidebar_status(tokens)
    body_fn(tokens)
