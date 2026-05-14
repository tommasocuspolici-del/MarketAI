"""Stress test viewer — scenario table + impact bar chart."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from engine.stress_testing import StressTestReport
    from presentation.ui.theme import DesignTokens

__version__ = "6.0.0"

__all__ = [
    "build_impact_chart",
    "build_scenario_table",
    "render_stress_test_viewer",
]


def build_scenario_table(report: StressTestReport) -> pd.DataFrame:
    """Build a DataFrame of scenarios with their final loss + severity."""
    rows = []
    for outcome in report.outcomes:
        rows.append({
            "Scenario": outcome.scenario.name,
            "Type": outcome.scenario.scenario_type.value,
            "Equity Shock": f"{outcome.scenario.equity_shock_pct:+.1%}",
            "Bond Shock": f"{outcome.scenario.bond_shock_pct:+.1%}",
            "Final Loss": f"{outcome.final_loss_pct:+.1%}",
            "Max Loss": f"{outcome.max_loss_pct:+.1%}",
            "Severity": outcome.severity,
            "Probability": (
                f"{outcome.scenario.probability:.1%}"
                if outcome.scenario.probability is not None else "—"
            ),
        })
    return pd.DataFrame(rows)


def build_impact_chart(
    tokens: DesignTokens, report: StressTestReport
) -> Any:
    """Bar chart of scenarios sorted by max_loss (worst-first)."""
    import plotly.graph_objects as go

    sorted_outcomes = sorted(report.outcomes, key=lambda o: o.max_loss_pct)
    names = [o.scenario.name for o in sorted_outcomes]
    losses = [o.max_loss_pct * 100 for o in sorted_outcomes]
    colors = [
        tokens.colors.negative if o.is_negative else tokens.colors.positive
        for o in sorted_outcomes
    ]

    fig = go.Figure(
        go.Bar(
            x=losses, y=names,
            orientation="h",
            marker={"color": colors},
            name="Max Loss %",
        )
    )
    fig.update_layout(
        title="Scenario Impact — Max Loss %",
        template=tokens.plotly.template,
        paper_bgcolor=tokens.plotly.paper_bgcolor,
        plot_bgcolor=tokens.plotly.plot_bgcolor,
        font={"family": tokens.plotly.font_family, "color": tokens.plotly.font_color},
        height=tokens.plotly.height_lg,
        xaxis_title="Max Loss %",
        showlegend=False,
    )
    return fig


def render_stress_test_viewer(
    tokens: DesignTokens, report: StressTestReport
) -> None:  # pragma: no cover
    """Render scenarios table + impact chart + alerts."""
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso
    import streamlit as st  # pragma: no cover

    # KPI summary
    cols = st.columns(4)
    cols[0].metric("VaR 95%", f"{report.var_95:+.1%}")
    cols[1].metric("CVaR 95%", f"{report.cvar_95:+.1%}")
    cols[2].metric("P(Negative)", f"{report.prob_negative:.1%}")
    cols[3].metric("# Scenarios", str(report.n_scenarios))

    # Alerts
    for alert in report.alerts:
        if alert.severity == "critical":
            st.error(f"🚨 **CRITICAL**: {alert.message}")
        else:
            st.warning(f"⚠️ {alert.message}")

    # Impact chart
    st.plotly_chart(
        build_impact_chart(tokens, report), use_container_width=True
    )

    # Scenario table
    st.dataframe(
        build_scenario_table(report),
        use_container_width=True,
        hide_index=True,
    )
