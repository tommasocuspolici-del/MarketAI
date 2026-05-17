# ruff: noqa: N999
"""E13 — Stress Test page (scenarios viewer + impact + what-if)."""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from engine.stress_testing import MarketContext, StressTester, StressTestReport
from presentation.ui.components.stress_test_viewer import render_stress_test_viewer
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "6.0.0"

__all__ = ["body_stress_test", "build_mock_stress_report"]


def build_mock_stress_report() -> StressTestReport:
    n = 252
    equity = pd.Series(np.linspace(10_000, 11_500, n))
    ctx = MarketContext(
        vix=20.0, yield_curve_2y_10y=0.0,
        sentiment_composite=0.1, regime="transition",
    )
    tester = StressTester()
    return tester.run(equity, ctx)


def body_stress_test(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit-rendered body
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st
    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="e13_refresh"):
            st.cache_data.clear()
            st.rerun()
    render_section_header("Market Context Sliders", "What-if scenario builder")
    cols = st.columns(3)
    cols[0].slider("VIX", 10.0, 60.0, 20.0)
    cols[1].slider("10Y-2Y Spread", -1.0, 2.0, 0.0, step=0.05)
    cols[2].select_slider("Regime", ["bull", "transition", "bear", "stress"])
    if st.button("Run Stress Test"):
        report = build_mock_stress_report()
        render_stress_test_viewer(tokens, report)


if __name__ == "__main__":   # pragma: no cover
    render_page("Stress Test", "💥", body_stress_test)
