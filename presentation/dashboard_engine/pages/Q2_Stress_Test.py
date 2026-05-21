# ruff: noqa: N999
"""Q2 — Stress Test & VaR/CVaR (Blocco D).

Pattern: _load_*() pure + body_stress_test() Streamlit.
2 tab: Scenari Storici · Metriche VaR/CVaR
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from presentation.ui.cache_policy import CACHE_TTL
from presentation.ui.components import EmptyState
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "1.0.0"
__all__ = ["body_stress_test"]

_SCENARIOS: list[dict] = [
    {"name": "2008 GFC",           "shock_pct": -55.0, "duration_days": 517, "description": "Crisi finanziaria globale — Lehman Brothers"},
    {"name": "COVID-19 2020",      "shock_pct": -34.0, "duration_days": 33,  "description": "Crash pandemico — S&P500 da feb a mar 2020"},
    {"name": "2022 Rate Shock",    "shock_pct": -25.0, "duration_days": 282, "description": "Rialzo tassi Fed — bear market 2022"},
    {"name": "Dot-com 2000-2002",  "shock_pct": -49.0, "duration_days": 929, "description": "Bolla tecnologica — Nasdaq -78%"},
    {"name": "Flash Crash 2010",   "shock_pct": -10.0, "duration_days": 1,   "description": "Flash crash intraday 6 maggio 2010"},
]


def _load_stress_scenarios() -> list[dict]:
    return list(_SCENARIOS)


def _load_risk_metrics(ticker: str) -> dict:
    try:
        from engine.risk.cvar_calculator import CVaRCalculator
        from shared.db.duckdb_client import get_duckdb_client
        from shared.db.prices_repo import PricesRepository

        db = get_duckdb_client()
        repo = PricesRepository(db)
        calc = CVaRCalculator(prices_repo=repo, duckdb=db)
        m = calc.compute(ticker, "NASDAQ")
        return {
            "var_95":   m.var_95_tstudent,
            "cvar_95":  m.cvar_95,
            "var_99":   m.var_99_tstudent,
            "cvar_99":  m.cvar_99,
            "skewness": m.skewness,
            "kurtosis": m.kurtosis,
            "data_quality": m.data_quality_score,
        }
    except Exception:
        return {}


def body_stress_test(tokens: DesignTokens) -> None:  # pragma: no cover
    import streamlit as st

    render_section_header("🧨 Stress Test & Risk Metrics", "Scenari storici e metriche VaR/CVaR")

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="q2_refresh"):
            st.cache_data.clear()
            st.rerun()

    ticker = st.text_input("Ticker per metriche rischio", value="SPY", key="q2_ticker")

    tab_scenarios, tab_var = st.tabs(["📉 Scenari Storici", "📐 VaR / CVaR"])

    with tab_scenarios:
        _render_scenarios_tab(st, ticker)

    with tab_var:
        _render_var_tab(st, ticker)


def _render_scenarios_tab(st, ticker: str) -> None:  # pragma: no cover
    import pandas as pd

    render_section_header("📉 Scenari Storici")
    portfolio_value = st.number_input("Valore portafoglio ($)", value=10_000, min_value=100, step=1_000, key="q2_pv")

    scenarios = _load_stress_scenarios()
    rows = []
    for s in scenarios:
        impact = portfolio_value * s["shock_pct"] / 100
        rows.append({
            "Scenario":     s["name"],
            "Shock %":      f"{s['shock_pct']:+.1f}%",
            "Durata (gg)":  s["duration_days"],
            "Impatto ($)":  f"${impact:,.0f}",
            "Descrizione":  s["description"],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption("⚠️ Stime basate su drawdown storici S&P500. Non costituiscono previsioni.")


def _render_var_tab(st, ticker: str) -> None:  # pragma: no cover
    @st.cache_data(ttl=CACHE_TTL.BACKTESTING)
    def _cached_metrics(t: str) -> dict:
        return _load_risk_metrics(t)

    with st.spinner(f"Calcolo metriche rischio per {ticker}..."):
        metrics = _cached_metrics(ticker)

    if not metrics:
        EmptyState(
            "Metriche non disponibili",
            hint=f"Dati OHLCV insufficienti per {ticker} o DB non raggiungibile.",
            severity="warning",
        ).render()
        return

    render_section_header("📐 Metriche di Rischio")
    cols = st.columns(4)
    items = [
        ("VaR 95% (1g)",  f"{metrics['var_95']*100:.2f}%",  "Perdita massima giornaliera al 95° percentile"),
        ("CVaR 95%",      f"{metrics['cvar_95']*100:.2f}%", "Expected Shortfall — media perdite oltre VaR 95%"),
        ("VaR 99% (1g)",  f"{metrics['var_99']*100:.2f}%",  "Perdita massima giornaliera al 99° percentile"),
        ("Skewness",      f"{metrics['skewness']:.2f}",      "< 0 = code sinistre (rischio tail)"),
    ]
    for col, (label, value, help_text) in zip(cols, items, strict=False):
        with col:
            st.metric(label, value, help=help_text)

    dq = metrics.get("data_quality", 0.0)
    st.caption(f"Data quality score: {dq:.2f} · Kurtosis: {metrics.get('kurtosis', 0):.2f}")


if __name__ == "__main__":  # pragma: no cover
    render_page("Stress Test", "🧨", body_stress_test)
