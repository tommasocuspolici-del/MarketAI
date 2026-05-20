"""UI components package — composable visual building blocks (Rule 20).

Legacy pattern (v6.0): ``build_*()`` pure function + ``render_*()`` Streamlit wrapper.
New pattern (v8.2): ``BaseComponent`` subclasses with ``to_html()`` + ``render()``.

Both patterns coexist. New pages use the class-based components.
"""
from __future__ import annotations

# ── New class-based components (v8.2) ─────────────────────────────────────
from presentation.ui.components.base import BaseComponent
from presentation.ui.components.empty_state import EmptyState
from presentation.ui.components.section_header import SectionHeader
from presentation.ui.components.signal_badge import SignalBadge
from presentation.ui.components.status_dot import StatusDot

# ── Legacy functional components (v6.0) ───────────────────────────────────
from presentation.ui.components.backtest_report import render_backtest_report
from presentation.ui.components.candlestick_pro import render_candlestick_pro
from presentation.ui.components.cash_flow_waterfall import render_cash_flow_waterfall
from presentation.ui.components.correlation_network import render_correlation_network
from presentation.ui.components.data_quality_badge import render_data_quality_badge
from presentation.ui.components.goal_tracker import (
    render_goal_tracker,
    render_goals_list,
)
from presentation.ui.components.health_status_bar import render_health_status_bar
from presentation.ui.components.kpi_card import render_kpi_card, render_kpi_row
from presentation.ui.components.latency_indicator import render_latency_indicator
from presentation.ui.components.net_worth_chart import render_net_worth_chart
from presentation.ui.components.pipeline_stepper import (
    PipelineStep,
    render_pipeline_stepper,
)
from presentation.ui.components.profile_card import render_profile_card
from presentation.ui.components.regime_badge import render_regime_badge
from presentation.ui.components.sentiment_radar import render_sentiment_radar
from presentation.ui.components.stress_test_viewer import render_stress_test_viewer
from presentation.ui.components.wealth_scenario_chart import render_wealth_scenario_chart

__version__ = "8.2.0"

__all__ = [
    # v8.2 class-based
    "BaseComponent",
    "EmptyState",
    "SectionHeader",
    "SignalBadge",
    "StatusDot",
    # v6.0 functional
    "PipelineStep",
    "render_backtest_report",
    "render_candlestick_pro",
    "render_cash_flow_waterfall",
    "render_correlation_network",
    "render_data_quality_badge",
    "render_goal_tracker",
    "render_goals_list",
    "render_health_status_bar",
    "render_kpi_card",
    "render_kpi_row",
    "render_latency_indicator",
    "render_net_worth_chart",
    "render_pipeline_stepper",
    "render_profile_card",
    "render_regime_badge",
    "render_sentiment_radar",
    "render_stress_test_viewer",
    "render_wealth_scenario_chart",
]
