"""Data quality badge — visualizes a DataQualityReport score (Rule 26)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens
    from shared.db.quality import DataQualityReport

__version__ = "6.0.0"

__all__ = ["build_quality_badge_html", "render_data_quality_badge"]


def build_quality_badge_html(tokens: DesignTokens, score: float) -> str:
    """Build HTML for a quality badge."""
    color = tokens.colors.for_quality_score(score)
    label = "EXCELLENT" if score >= 0.9 else "GOOD" if score >= 0.7 else "FAIR" if score >= 0.5 else "POOR"
    return (
        f'<span class="market-ai-quality-badge" '
        f'style="background-color: {color}33; color: {color}; '
        f'border: 1px solid {color};">'
        f"{label} {score:.2f}"
        "</span>"
    )


def render_data_quality_badge(
    tokens: DesignTokens,
    report: DataQualityReport,
) -> None:  # pragma: no cover
    """Render a quality badge for a series."""
    html = build_quality_badge_html(tokens, report.quality_score)

    try:  # pragma: no cover
        import streamlit as st
        st.markdown(html, unsafe_allow_html=True)
        if report.quality_score < 0.7:
            st.caption(
                f"⚠️ Quality below recommended threshold for analytics. "
                f"Series: {report.series_id}"
            )
    except ImportError:
        return  # pragma: no cover
