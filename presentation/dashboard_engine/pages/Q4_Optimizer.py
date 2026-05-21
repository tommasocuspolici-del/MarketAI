# ruff: noqa: N999
"""Q4 — Portfolio Optimizer (Blocco D).

Pattern: _load_*() pure + body_optimizer() Streamlit.
2 tab: Configura · Report
"""
from __future__ import annotations

from presentation.ui.cache_policy import CACHE_TTL
from presentation.ui.components import EmptyState
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "1.0.0"
__all__ = ["body_optimizer"]

_METHODS = ["hrp", "equal_weight", "risk_parity", "markowitz"]
_SESSION_KEY = "q4_optimizer_report"


def _load_optimization_report() -> dict:
    """Carica l'ultimo report di ottimizzazione dalla session o fallback vuoto."""
    return {}


def body_optimizer(tokens: DesignTokens) -> None:  # pragma: no cover
    import streamlit as st

    render_section_header("⚙️ Portfolio Optimizer", "HRP · Equal Weight · Risk Parity · Markowitz")

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="q4_refresh"):
            st.session_state.pop(_SESSION_KEY, None)
            st.rerun()

    tab_config, tab_report = st.tabs(["⚙️ Configura", "📋 Report"])

    with tab_config:
        _render_config_tab(st, tokens)

    with tab_report:
        _render_report_tab(st, tokens)


def _render_config_tab(st, tokens: DesignTokens) -> None:  # pragma: no cover
    from engine.portfolio.rebalancing_engine import RebalancingEngine
    from shared.db.duckdb_client import get_duckdb_client

    render_section_header("Configurazione Ottimizzazione")

    col1, col2 = st.columns(2)
    with col1:
        tickers_raw = st.text_area(
            "Tickers (uno per riga)", value="SPY\nQQQ\nGLD\nTLT", key="q4_tickers", height=120,
        )
        method = st.selectbox("Metodo", _METHODS, key="q4_method")
    with col2:
        portfolio_value = st.number_input("Valore portafoglio (€)", value=10_000, min_value=100, step=500, key="q4_pv")
        risk_profile = st.selectbox("Profilo rischio", ["conservative", "moderate", "aggressive"], index=1, key="q4_risk")

    tickers = [t.strip() for t in tickers_raw.splitlines() if t.strip()]
    equal_w = 1.0 / len(tickers) if tickers else 0.0
    current_weights = {t: equal_w for t in tickers}

    if st.button("⚙️ Ottimizza", type="primary", key="q4_run", disabled=len(tickers) < 2):
        with st.spinner("Ottimizzazione in corso..."):
            try:
                db = get_duckdb_client()
                engine = RebalancingEngine(
                    duckdb=db,
                    profile_risk=risk_profile,
                    method=method,
                )
                report = engine.run(
                    current_weights=current_weights,
                    portfolio_value_eur=float(portfolio_value),
                    profile_id="q4_session",
                )
                st.session_state[_SESSION_KEY] = report
                st.success(f"✅ Ottimizzazione completata — {report.n_trades} trade suggeriti")
                st.rerun()
            except Exception as exc:
                st.error(f"❌ Errore: {type(exc).__name__}: {str(exc)[:200]}")


def _render_report_tab(st, tokens: DesignTokens) -> None:  # pragma: no cover
    import pandas as pd

    report = st.session_state.get(_SESSION_KEY)
    if report is None:
        EmptyState(
            "Nessun report disponibile",
            hint="Vai al tab 'Configura', seleziona i parametri e clicca '⚙️ Ottimizza'.",
        ).render()
        return

    render_section_header("📋 Report Ottimizzazione")

    cols = st.columns(3)
    with cols[0]:
        st.metric("Turnover totale", f"{report.total_turnover_pct*100:.1f}%")
    with cols[1]:
        st.metric("Vol attesa (annua)", f"{report.expected_vol_annual*100:.1f}%")
    with cols[2]:
        st.metric("HHI (concentrazione)", f"{report.expected_hhi:.3f}")

    st.divider()
    render_section_header("Target Weights & Trade Instructions")

    if report.trades:
        rows = [
            {
                "Ticker":          tr.ticker,
                "Azione":          tr.action,
                "Peso corrente %": f"{tr.current_weight*100:.1f}%",
                "Peso target %":   f"{tr.target_weight*100:.1f}%",
                "Drift %":         f"{tr.drift_pct*100:.1f}%",
                "Importo (€)":     f"€{tr.estimated_eur:,.0f}",
            }
            for tr in report.trades
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.caption(report.summary)


if __name__ == "__main__":  # pragma: no cover
    render_page("Portfolio Optimizer", "⚙️", body_optimizer)
