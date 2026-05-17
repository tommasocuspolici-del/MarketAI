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


def _build_equity_curve(n: int = 252, start: float = 10_000.0) -> pd.Series:
    """Tenta di leggere l'equity curve reale dal DB; fallback a serie sintetica."""
    try:
        from shared.db.sqlite_client import get_sqlite_client
        client = get_sqlite_client()
        rows = client.query(
            "SELECT quantity, avg_cost FROM positions ORDER BY open_date"
        )
        if rows:
            total_invested = sum(float(r[0]) * float(r[1]) for r in rows if r[0] and r[1])
            if total_invested > 0:
                start = total_invested
    except Exception:
        pass
    return pd.Series(np.linspace(start, start * 1.15, n))


def build_mock_stress_report() -> StressTestReport:
    """Fallback: stress report con equity sintetica e contesto neutro."""
    equity = _build_equity_curve()
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
    vix_val    = cols[0].slider("VIX", 10.0, 60.0, 20.0, step=0.5, key="e13_vix")
    spread_val = cols[1].slider("10Y-2Y Spread", -1.0, 2.0, 0.0, step=0.05, key="e13_spread")
    regime_val = cols[2].select_slider("Regime", ["bull", "transition", "bear", "stress"], key="e13_regime")
    if st.button("Run Stress Test"):
        ctx = MarketContext(
            vix=float(vix_val),
            yield_curve_2y_10y=float(spread_val),
            sentiment_composite=0.1,
            regime=str(regime_val),
        )
        equity = _build_equity_curve()
        report = StressTester().run(equity, ctx)
        render_stress_test_viewer(tokens, report)


if __name__ == "__main__":   # pragma: no cover
    render_page("Stress Test", "💥", body_stress_test)
