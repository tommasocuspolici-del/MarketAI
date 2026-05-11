# ruff: noqa: N999
"""E14 — Alerts page (active list + thresholds + history)."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "6.0.0"

__all__ = ["body_alerts"]


def body_alerts(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit-rendered body
    try:  # pragma: no cover
        import streamlit as st
    except ImportError:
        return
    render_section_header("Active Alerts")
    st.dataframe(pd.DataFrame({
        "Severity":   ["🔴 Critical", "🟡 Warning", "🟡 Warning"],
        "Type":       ["VaR breach",   "Sentiment extreme", "Vol spike"],
        "Detail":     ["Portfolio VaR -8% > -5% threshold",
                       "AAII bullishness 78% (>75% extreme)",
                       "VIX spike 22 → 28 in 1h"],
        "Triggered":  ["2 hours ago", "1 day ago", "2 days ago"],
    }), use_container_width=True, hide_index=True)
    render_section_header("Alert Configuration")
    cols = st.columns(2)
    cols[0].number_input("VaR 95% threshold (%)", value=-5.0, step=0.5)
    cols[1].number_input("Sentiment extreme threshold", value=0.75, step=0.05)


if __name__ == "__main__":   # pragma: no cover
    render_page("Alerts", "🚨", body_alerts)
