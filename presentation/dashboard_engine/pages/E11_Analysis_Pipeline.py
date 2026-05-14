# ruff: noqa: N999
"""E11 — Analysis Pipeline (stepper + manual refresh + log)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from presentation.ui.components.pipeline_stepper import (
    PipelineStep,
    render_pipeline_stepper,
)
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "6.0.0"

__all__ = ["body_analysis_pipeline"]


def body_analysis_pipeline(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit-rendered body
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st
    render_section_header("Pipeline State", "Last run for selected ticker")
    ticker = st.selectbox("Ticker", ["AAPL", "MSFT", "GOOGL"])
    steps = [
        PipelineStep(name="Fetch",    status="success", duration_ms=420.0),
        PipelineStep(name="Clean",    status="success", duration_ms=85.0),
        PipelineStep(name="Validate", status="success", duration_ms=22.0),
        PipelineStep(name="DuckDB",   status="success", duration_ms=110.0),
        PipelineStep(name="Cache",    status="success", duration_ms=3.0),
    ]
    render_pipeline_stepper(tokens, steps)
    st.write("")
    if st.button(f"🔄 Trigger refresh for {ticker}"):
        st.success(f"Refresh triggered for {ticker} — check logs")
    render_section_header("Recent Operations")
    st.code("[OK] AAPL fetch+clean+validate+write 642ms\n"
            "[OK] MSFT fetch+clean+validate+write 580ms\n"
            "[OK] GOOGL fetch+clean+validate+write 615ms")


if __name__ == "__main__":   # pragma: no cover
    render_page("Analysis Pipeline", "⚙️", body_analysis_pipeline)
