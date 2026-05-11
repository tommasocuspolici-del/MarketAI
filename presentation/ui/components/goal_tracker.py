"""Goal tracker — progress bar + status for SMART goals."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from personal.goals import Goal
    from presentation.ui.theme import DesignTokens

__version__ = "6.0.0"

__all__ = ["build_goal_tracker_html", "render_goal_tracker", "render_goals_list"]


def build_goal_tracker_html(tokens: DesignTokens, goal: Goal) -> str:
    """Build HTML for a single goal progress card."""
    c = tokens.colors
    progress_pct = min(goal.progress_pct, 1.0) * 100
    bar_color = (
        c.positive if goal.is_achieved
        else c.warning if progress_pct >= 50
        else c.accent_primary
    )

    days = goal.days_to_target
    days_text = (
        f"{days} days remaining" if days > 0
        else f"⚠️ {abs(days)} days overdue"
    )

    return (
        '<div class="market-ai-kpi-card">'
        f'<div style="display: flex; justify-content: space-between; '
        f'align-items: center; margin-bottom: {tokens.spacing.unit_sm};">'
        f'<div class="market-ai-kpi-label">{goal.name}</div>'
        f'<div style="color: {bar_color}; font-weight: '
        f'{tokens.typography.font_weight_semibold};">'
        f"{progress_pct:.1f}%"
        "</div>"
        "</div>"
        f'<div style="background-color: {c.bg_overlay}; height: 8px; '
        f'border-radius: {tokens.borders.radius_sm}; overflow: hidden;">'
        f'<div style="background-color: {bar_color}; width: {progress_pct}%; '
        f'height: 100%;"></div>'
        "</div>"
        f'<div style="margin-top: {tokens.spacing.unit_sm}; '
        f'font-size: {tokens.typography.font_size_sm}; color: {c.text_secondary};">'
        f"<span>{tokens.formats.currency_eur.format(value=goal.current_amount)} / "
        f"{tokens.formats.currency_eur.format(value=goal.target_amount)}</span>"
        f' &nbsp;·&nbsp; <span>{days_text}</span>'
        "</div>"
        "</div>"
    )


def render_goal_tracker(tokens: DesignTokens, goal: Goal) -> None:  # pragma: no cover
    """Render a single goal tracker card."""
    html = build_goal_tracker_html(tokens, goal)
    try:  # pragma: no cover
        import streamlit as st
        st.markdown(html, unsafe_allow_html=True)
    except ImportError:
        return  # pragma: no cover


def render_goals_list(tokens: DesignTokens, goals: list[Goal]) -> None:  # pragma: no cover
    """Render a vertical list of goal trackers."""
    try:  # pragma: no cover
        import streamlit as st
    except ImportError:
        return  # pragma: no cover

    if not goals:
        st.info("Nessun obiettivo definito. Crea il tuo primo obiettivo SMART.")
        return

    for goal in goals:
        render_goal_tracker(tokens, goal)
        st.write("")  # spacing
