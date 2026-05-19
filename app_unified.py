"""
MarketAI · Unified Dashboard Entry Point — v11.0 (Roadmap Unificata Fase 1)
============================================================================

Migrazione completa da E1..E14 alla struttura K/M/N/Q/S/T (Fase 1).

Sezioni:
  📡 SISTEMA        — S0 Health, S1 Pipeline, S2 Settings
  🌍 MACRO & CICLO  — M1..M7 (macro, yield curve, labour, PMI, surprise, P/E, IB)
  📊 MERCATI        — K1..K5 (overview, equity, bonds, commodity, forex)
  🔬 ANALISI QUANT  — Q1..Q11 (VIX, sentiment, correlations, forecast, delta...)
  📰 NEWS & IB      — N1 News Feed, N2 News Analysis
  ⚙️ STRATEGIE      — T1 Backtesting, T2 Stress Test, T3 Alerts
  💼 PERSONAL       — P1..P9 (patrimonio, portafoglio, cashflow, obiettivi, fiscal)

Engine pages usano pages_v2/ (signature: body_fn(st, tokens)).
Personal pages usano pages/ (signature: body_fn(tokens), chiamata via render_page).

Avvio:
  poetry run streamlit run app_unified.py

Richiede Streamlit >= 1.36 per st.navigation() e st.Page(callable).
"""
from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path

import streamlit as st

# ── Startup: .env → migrations SQLite → migrations DuckDB ──────────────────
from shared.env_loader import get_api_key_statuses, load_environment

_ENV_REPORT = load_environment()

from shared.db.migrations_runner import apply_sqlite_migrations
from shared.db.duckdb_migrator import run_pending_migrations

_MIGRATIONS_REPORT = apply_sqlite_migrations()

try:
    run_pending_migrations()
except Exception:
    pass  # non-fatal

# ── Auth gating (Rule 32) ───────────────────────────────────────────────────
try:
    from presentation.ui.auth import require_auth
except ImportError:
    def require_auth() -> None:  # type: ignore[misc]
        return

# ── Page config (prima chiamata Streamlit) ──────────────────────────────────
st.set_page_config(
    page_title="MarketAI · Professional Edition",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

require_auth()

ROOT = Path(__file__).parent


# ── Helpers ─────────────────────────────────────────────────────────────────

def _engine_page(module_name: str) -> Callable[[], None]:
    """Callable che renderizza un engine page da pages_v2/.

    Streamlit 1.36+ supporta st.Page(callable) — il callable viene eseguito
    quando la pagina è selezionata.
    """
    def _render() -> None:
        try:
            mod = importlib.import_module(
                f"presentation.dashboard_engine.pages_v2.{module_name}"
            )
            fn_name = f"body_{module_name.lower()}"
            if hasattr(mod, fn_name):
                from presentation.ui.theme import get_design_tokens
                getattr(mod, fn_name)(st, get_design_tokens())
            else:
                st.info(f"Pagina `{module_name}` in costruzione.")
        except ModuleNotFoundError:
            st.info(f"Modulo `{module_name}` non trovato.")
        except Exception as exc:
            st.error(f"Errore rendering `{module_name}`: {exc}")
    return _render


def _personal_page(rel_path: str, title: str, icon: str) -> "st.Page | None":
    """st.Page da file path per pagine personal (self-contained con render_page)."""
    full = ROOT / rel_path
    if not full.exists():
        return None
    return st.Page(str(full), title=title, icon=icon)


def _ep(module: str, title: str, icon: str) -> "st.Page":
    """Shorthand: crea st.Page da callable per engine page."""
    return st.Page(_engine_page(module), title=title, icon=icon)


# ── Navigation registry ─────────────────────────────────────────────────────
PER = "presentation/dashboard_personal/pages"

nav_dict: dict[str, list] = {
    "📡 SISTEMA": [
        _ep("S0_Health_API_Status",       "Health & API Status", "📡"),
        _ep("S1_Analysis_Pipeline",       "Analysis Pipeline",   "⚙️"),
        _ep("S2_Settings",                "Impostazioni",        "🔧"),
    ],
    "🌍 MACRO & CICLO": [
        _ep("M1_Macro_Dashboard",         "Macro Dashboard ★",   "🏛️"),
        _ep("M2_Yield_Curve",             "Yield Curve",         "📐"),
        _ep("M3_Labour_Market",           "Labour Market ★",     "👷"),
        _ep("M4_PMI_Leading_Indicators",  "PMI & Leading Ind.",  "📊"),
        _ep("M5_Economic_Surprise",       "Economic Surprise ★", "⚡"),
        _ep("M6_Valuation_PE",            "Valuation & P/E ★",   "💰"),
        _ep("M7_IB_Consensus",            "IB Consensus ★",      "🏦"),
    ],
    "📊 MERCATI": [
        _ep("K1_Market_Overview",         "Market Overview ★",   "🌍"),
        _ep("K2_Equity",                  "Equity",              "📈"),
        _ep("K3_Bonds_Credit",            "Bonds & Credit",      "📉"),
        _ep("K4_Commodity_Futures",       "Commodity & Futures ★","🛢️"),
        _ep("K5_Forex_Options",           "Forex & Opzioni",     "💱"),
    ],
    "🔬 ANALISI QUANTITATIVA": [
        _ep("Q1_VIX_Based_Analysis",      "VIX-Based ★",         "📉"),
        _ep("Q2_Sentiment",               "Sentiment Radar",     "🌡️"),
        _ep("Q3_Correlations",            "Correlazioni",        "🕸️"),
        _ep("Q4_Forecasting",             "Forecasting",         "🔮"),
        _ep("Q5_Delta",                   "Delta & Momentum",    "📈"),
        _ep("Q9_Labour_Forecasting",      "Labour Forecasting ★","🔬"),
        _ep("Q10_Surprise_Heatmap",       "Surprise Heatmap ★",  "🗺️"),
        _ep("Q11_Options_Analytics",      "Options Analytics",   "📊"),
    ],
    "📰 NEWS & IB FORECAST": [
        _ep("N1_News_Feed",               "News Feed ★",         "📰"),
        _ep("N2_News_Analysis",           "News Analysis ★",     "📊"),
    ],
    "⚙️ STRATEGIE": [
        _ep("T1_Backtesting",             "Backtesting",         "🧪"),
        _ep("T2_Stress_Test",             "Stress Test",         "⚡"),
        _ep("T3_Alerts",                  "Alert Mercato",       "🚨"),
    ],
}

# Personal pages — file-based (self-contained con render_page)
_personal = [p for p in [
    _personal_page(f"{PER}/P1_Overview_Patrimonio.py", "Overview Patrimonio", "💼"),
    _personal_page(f"{PER}/P4_Net_Worth.py",           "Net Worth",           "💰"),
    _personal_page(f"{PER}/P2_Portafoglio_eToro.py",   "Portafoglio eToro",   "📂"),
    _personal_page(f"{PER}/P3_Cash_Flow.py",           "Cash Flow",           "💸"),
    _personal_page(f"{PER}/P5_Goals.py",               "Obiettivi SMART",     "🎯"),
    _personal_page(f"{PER}/P7_Scenari_Ricchezza.py",   "Scenari Ricchezza",   "🔭"),
    _personal_page(f"{PER}/P6_Profilo_Investitore.py", "Profilo Investitore", "🧭"),
    _personal_page(f"{PER}/P8_Fiscale.py",             "Fiscale (IT)",        "🧾"),
    _personal_page(f"{PER}/P9_Alerts_Personali.py",    "Alert Personali",     "🔔"),
] if p is not None]

if _personal:
    nav_dict["💼 PERSONAL · Patrimonio"] = _personal


# ── Sidebar branding ─────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🧠 MarketAI")
    st.caption("Professional Edition · v11.0")
    st.divider()

    if _MIGRATIONS_REPORT.error is not None:
        st.error(
            f"⚠️ **Migrazioni DB SQLite fallite:** {_MIGRATIONS_REPORT.error}\n\n"
            "Esegui manualmente: `poetry run alembic upgrade head`"
        )
    elif _MIGRATIONS_REPORT.applied:
        st.caption("✅ DB migrations: ok")

    if not _ENV_REPORT.loaded_successfully:
        st.warning(
            "⚠️ **Nessun file `.env` trovato.** "
            "Le API esterne (FRED, Alpha Vantage, Finnhub, eToro) saranno "
            "disabilitate. Crea `.env` partendo da `.env.example`."
        )
    else:
        _statuses = get_api_key_statuses()
        _n_usable = sum(1 for s in _statuses if s.is_usable)
        _n_total = len(_statuses)
        if _n_usable < _n_total:
            st.caption(
                f"🔑 API keys: **{_n_usable}/{_n_total}** configurate · "
                f".env: `{_ENV_REPORT.dotenv_path.name}`"
            )
        else:
            st.caption(f"✅ {_n_total} API keys configurate · `.env` ok")

    # Composite Signal live (best-effort)
    try:
        from shared.db.duckdb_client import get_duckdb_client
        rows = get_duckdb_client().query(
            "SELECT composite_score, recommended_action "
            "FROM engine_composite_signal ORDER BY computed_at DESC LIMIT 1"
        )
        if rows:
            score  = float(rows[0][0])
            action = str(rows[0][1])
            label  = "🟢 BUY" if score > 0.2 else ("🔴 SELL" if score < -0.2 else "⚪ HOLD")
            st.divider()
            st.metric("Composite Signal", f"{score:+.3f}", label)
            st.caption(f"Azione: **{action}**")
    except Exception:
        pass

    # Health bar (best-effort)
    try:
        from presentation.ui.components.health_status_bar import render_health_status_bar
        from presentation.ui.theme import DESIGN_TOKENS
        from shared.health import HealthChecker
        from shared.db.duckdb_client import get_duckdb_client
        from shared.db.sqlite_client import get_sqlite_client
        health = HealthChecker(
            duckdb_client=get_duckdb_client(),
            sqlite_client=get_sqlite_client(),
            cache_manager=None,
        ).check_all()
        render_health_status_bar(DESIGN_TOKENS, health)
    except Exception:
        st.caption("🟢 Sistema attivo")


# ── Esegui navigazione ───────────────────────────────────────────────────────
if not nav_dict:
    st.error(
        "❌ Nessuna pagina trovata. Verifica che la struttura "
        "`presentation/dashboard_engine/pages_v2/` esista."
    )
    st.stop()

pg = st.navigation(nav_dict, position="sidebar")
pg.run()
