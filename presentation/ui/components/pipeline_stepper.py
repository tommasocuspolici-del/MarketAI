"""Pipeline stepper — visual progress for the fetch→clean→validate→DB pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "6.0.0"

__all__ = ["PipelineStep", "render_pipeline_stepper"]


@dataclass(frozen=True, slots=True)
class PipelineStep:
    """One stage in a pipeline visualization."""

    name: str
    status: str   # "pending" | "running" | "success" | "failed"
    duration_ms: float | None = None
    message: str | None = None


def _step_color(tokens: DesignTokens, status: str) -> str:
    return {
        "pending": tokens.colors.text_muted,
        "running": tokens.colors.accent_primary,
        "success": tokens.colors.positive,
        "failed":  tokens.colors.negative,
    }.get(status, tokens.colors.neutral)


def _step_icon(status: str) -> str:
    return {"pending": "⚪", "running": "🔵", "success": "🟢", "failed": "🔴"}.get(
        status, "⚪"
    )


def render_pipeline_stepper(
    tokens: DesignTokens, steps: list[PipelineStep]
) -> None:  # pragma: no cover
    """Render a horizontal stepper of pipeline stages."""
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso
    import streamlit as st  # pragma: no cover

    cols = st.columns(len(steps))
    for col, step in zip(cols, steps, strict=True):
        with col:
            color = _step_color(tokens, step.status)
            icon = _step_icon(step.status)
            duration = (
                f"<br><small>{step.duration_ms:.0f}ms</small>"
                if step.duration_ms is not None
                else ""
            )
            html = (
                f'<div style="text-align: center; padding: '
                f"{tokens.spacing.unit_sm}; "
                f'border-left: 3px solid {color};">'
                f'<div style="font-size: {tokens.typography.font_size_xl};">{icon}</div>'
                f'<div style="color: {color}; font-weight: '
                f'{tokens.typography.font_weight_semibold};">{step.name}</div>'
                f"{duration}"
                "</div>"
            )
            st.markdown(html, unsafe_allow_html=True)
            if step.message:
                st.caption(step.message)
