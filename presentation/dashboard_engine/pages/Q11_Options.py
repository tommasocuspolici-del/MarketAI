# ruff: noqa: N999
"""Q11 — Options Analytics (Blocco D).

Stub completo con EmptyState + preview Greeks table via st.dataframe.
Backend options engine non ancora implementato (Phase future).
"""
from __future__ import annotations

import pandas as pd

from presentation.ui.cache_policy import CACHE_TTL
from presentation.ui.components import EmptyState
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "1.0.0"
__all__ = ["body_options"]

_DEMO_GREEKS = [
    {"Strike": 500, "Exp": "2026-06-20", "Type": "Call", "Delta": 0.52, "Gamma": 0.018, "Theta": -0.12, "Vega": 0.38, "IV %": 18.4},
    {"Strike": 510, "Exp": "2026-06-20", "Type": "Call", "Delta": 0.38, "Gamma": 0.021, "Theta": -0.14, "Vega": 0.41, "IV %": 19.1},
    {"Strike": 490, "Exp": "2026-06-20", "Type": "Put",  "Delta": -0.48, "Gamma": 0.017, "Theta": -0.11, "Vega": 0.36, "IV %": 20.2},
    {"Strike": 480, "Exp": "2026-06-20", "Type": "Put",  "Delta": -0.35, "Gamma": 0.014, "Theta": -0.09, "Vega": 0.29, "IV %": 21.5},
]


def _load_options_chain(ticker: str) -> list[dict]:
    """Carica la catena opzioni dal DB. Ritorna lista vuota se non disponibile."""
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
        rows = db.query(
            "SELECT strike, expiration, option_type, delta, gamma, theta, vega, implied_vol "
            "FROM options_chain WHERE ticker = ? ORDER BY expiration, strike",
            [ticker],
        )
        if not rows:
            return []
        return [
            {"Strike": r[0], "Exp": str(r[1]), "Type": r[2],
             "Delta": r[3], "Gamma": r[4], "Theta": r[5], "Vega": r[6], "IV %": r[7]}
            for r in rows
        ]
    except Exception:
        return []


def _load_vol_surface(ticker: str) -> pd.DataFrame:
    """Carica la vol surface dal DB (strike × maturity)."""
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
        rows = db.query(
            "SELECT strike, days_to_exp, implied_vol FROM vol_surface WHERE ticker = ? ORDER BY days_to_exp, strike",
            [ticker],
        )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["strike", "days_to_exp", "implied_vol"])
        return df.pivot(index="strike", columns="days_to_exp", values="implied_vol")
    except Exception:
        return pd.DataFrame()


def body_options(tokens: DesignTokens) -> None:  # pragma: no cover
    import streamlit as st

    render_section_header("📈 Options Analytics", "Greeks · Vol Surface · Open Interest")

    cols_top = st.columns([3, 1, 1])
    with cols_top[1]:
        ticker = st.text_input("Ticker", value="SPY", key="q11_ticker", label_visibility="collapsed")
    with cols_top[2]:
        if st.button("🔄 Aggiorna", key="q11_refresh"):
            st.cache_data.clear()
            st.rerun()

    tab_greeks, tab_surface = st.tabs(["📐 Greeks", "🌡 Vol Surface"])

    with tab_greeks:
        _render_greeks_tab(st, ticker, tokens)

    with tab_surface:
        _render_surface_tab(st, ticker, tokens)


def _render_greeks_tab(st, ticker: str, tokens: DesignTokens) -> None:  # pragma: no cover
    @st.cache_data(ttl=CACHE_TTL.MARKET_KPI)
    def _cached(t: str) -> list[dict]:
        return _load_options_chain(t)

    chain = _cached(ticker)

    if not chain:
        st.warning("⚠️ Dati opzioni non presenti nel DB. Anteprima con dati demo:")
        st.dataframe(pd.DataFrame(_DEMO_GREEKS), use_container_width=True, hide_index=True)
        st.caption("🔧 Il backend options engine sarà disponibile in una fase futura. "
                   "Integrazione prevista con Interactive Brokers API.")
        return

    render_section_header("Greeks — Catena Opzioni")
    df = pd.DataFrame(chain)
    st.dataframe(df, use_container_width=True, hide_index=True)


def _render_surface_tab(st, ticker: str, tokens: DesignTokens) -> None:  # pragma: no cover
    from presentation.ui.chart_theme import ChartFactory
    import plotly.graph_objects as go
    import numpy as np

    @st.cache_data(ttl=CACHE_TTL.BACKTESTING)
    def _cached(t: str) -> pd.DataFrame:
        return _load_vol_surface(t)

    surf = _cached(ticker)

    if surf.empty:
        st.warning("⚠️ Vol Surface non disponibile nel DB. Anteprima con dati demo:")
        strikes = list(range(460, 541, 10))
        maturities = [7, 14, 30, 60, 90]
        z = np.array([[20 + 0.05 * abs(s - 500) + 0.02 * m for m in maturities] for s in strikes])
        fig = go.Figure(go.Surface(
            x=maturities, y=strikes, z=z,
            colorscale="Viridis", showscale=True,
        ))
        fig.update_layout(
            title="Vol Surface (DEMO)",
            scene=dict(xaxis_title="Days to Exp", yaxis_title="Strike", zaxis_title="IV %"),
            height=450, paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption("🔧 Dati dimostrativi. Il backend options engine sarà disponibile in una fase futura.")
        return

    render_section_header("Vol Surface")
    strikes = list(surf.index)
    maturities = list(surf.columns)
    z = surf.values
    fig = go.Figure(go.Surface(
        x=maturities, y=strikes, z=z,
        colorscale="Viridis", showscale=True,
    ))
    fig.update_layout(
        title=f"Implied Vol Surface — {ticker}",
        scene=dict(xaxis_title="Days to Exp", yaxis_title="Strike", zaxis_title="IV %"),
        height=450, paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)


if __name__ == "__main__":  # pragma: no cover
    render_page("Options Analytics", "📈", body_options)
