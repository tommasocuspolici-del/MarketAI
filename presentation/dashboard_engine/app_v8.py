"""MarketAI Dashboard Engine — v8.0 (Roadmap Unificata Settimane 6-7).

Navigazione S/M/K/Q/T che sostituisce E0-E14.

PAGES dict è importabile senza streamlit per i test di navigazione.
"""
from __future__ import annotations

import sys
from pathlib import Path

from presentation.ui.session_keys import SK

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

__version__ = "8.1.0"

# ─── Registry pagine (importabile senza streamlit) ────────────────────────────

PAGES: dict[str, list[tuple[str, str]]] = {
    "📡 SISTEMA": [
        ("S0 Health & API Status",   "S0_Health_API_Status"),
        ("S1 Analysis Pipeline",     "S1_Analysis_Pipeline"),
        ("S2 Settings",              "S2_Settings"),
    ],
    "🌍 MACRO & CICLO": [
        ("M1 Macro Dashboard",       "M1_Macro_Dashboard"),
        ("M2 Yield Curve",           "M2_Yield_Curve"),
        ("M3 Labour Market ★",       "M3_Labour_Market"),
        ("M4 PMI & Leading Ind. ★",  "M4_PMI_Leading_Indicators"),
        ("M5 Economic Surprise ★",   "M5_Economic_Surprise"),
        ("M6 Valuation P/E ★",       "M6_Valuation_PE"),
        ("M7 IB Consensus ★",        "M7_IB_Consensus"),
    ],
    "📊 MERCATI": [
        ("K1 Market Overview ★",     "K1_Market_Overview"),
        ("K2 Equity",                "K2_Equity"),
        ("K3 Bonds & Credit",        "K3_Bonds_Credit"),
        ("K4 Commodity & Futures ★", "K4_Commodity_Futures"),
        ("K5 Forex & Options",       "K5_Forex_Options"),
    ],
    "🔬 ANALISI QUANTITATIVA": [
        ("Q1 VIX-Based ★",           "Q1_VIX_Based_Analysis"),
        ("Q2 Sentiment",             "Q2_Sentiment"),
        ("Q3 Correlations",          "Q3_Correlations"),
        ("Q4 Forecasting",           "Q4_Forecasting"),
        ("Q5 Delta & Momentum",      "Q5_Delta"),
        ("Q9 Labour Forecasting ★",  "Q9_Labour_Forecasting"),
        ("Q10 Surprise Heatmap ★",   "Q10_Surprise_Heatmap"),
        ("Q11 Options Analytics",    "Q11_Options_Analytics"),
    ],
    "📰 NEWS & IB FORECAST": [
        ("N1 News Feed ★",           "N1_News_Feed"),
        ("N2 News Analysis ★",       "N2_News_Analysis"),
    ],
    "⚙️ STRATEGIE": [
        ("T1 Backtesting",           "T1_Backtesting"),
        ("T2 Stress Test",           "T2_Stress_Test"),
        ("T3 Alerts",                "T3_Alerts"),
    ],
}


def _render_page(active: str) -> None:
    """Renderizza la pagina attiva via import dinamico."""
    import importlib
    try:
        module  = importlib.import_module(
            f"presentation.dashboard_engine.pages_v2.{active}"
        )
        fn_name = f"body_{active.lower()}"
        if hasattr(module, fn_name):
            import streamlit as st
            from presentation.ui.theme import get_design_tokens
            getattr(module, fn_name)(st, get_design_tokens())
        else:
            import streamlit as st
            st.warning(f"Funzione `{fn_name}` non trovata in {active}.py")
    except ModuleNotFoundError:
        import streamlit as st
        st.info(f"Pagina {active} in costruzione.")
    except Exception as exc:
        import streamlit as st
        st.error(f"Errore: {exc}")


def main() -> None:  # pragma: no cover
    """Entry point per `streamlit run app_v8.py`."""
    import streamlit as st
    from presentation.ui.theme import get_design_tokens

    st.set_page_config(
        page_title="MarketAI v8.0", page_icon="📊",
        layout="wide", initial_sidebar_state="expanded",
    )

    with st.sidebar:
        st.markdown("## 📊 MarketAI v8.1")
        st.caption("Roadmap Unificata — Engine Dashboard")
        st.divider()

        for group, pages in PAGES.items():
            with st.expander(group, expanded=False):
                for label, module_name in pages:
                    if st.button(label, key=module_name, use_container_width=True):
                        st.session_state[SK.ACTIVE_PAGE] = module_name

        st.divider()
        try:
            from shared.db.duckdb_client import get_duckdb_client
            db   = get_duckdb_client()
            rows = db.query(
                "SELECT composite_score, recommended_action "
                "FROM engine_composite_signal ORDER BY computed_at DESC LIMIT 1"
            )
            if rows:
                score  = float(rows[0][0])
                action = str(rows[0][1])
                color  = "#10B981" if action == "BUY" else (
                         "#EF4444" if action == "REDUCE" else "#6B7280")
                st.markdown(
                    f'<div style="padding:8px;border-radius:6px;background:{color}22;'
                    f'border:1px solid {color};text-align:center">'
                    f'<div style="font-size:0.75rem;color:#9CA3AF">Composite Signal</div>'
                    f'<div style="font-weight:700;color:{color}">{action} {score:+.3f}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        except Exception:
            st.caption("⚪ DB non connesso")

    active = st.session_state.get(SK.ACTIVE_PAGE, "K1_Market_Overview")
    _render_page(active)


if __name__ == "__main__":
    main()
