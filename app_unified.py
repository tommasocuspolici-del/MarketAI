"""
MarketAI · Unified Dashboard Entry Point
========================================

Punto di ingresso unico che combina:
  · Engine Layer  (analisi quantitativa dei mercati)  — 14 pagine + E0
  · Personal Layer (gestione patrimonio personale)    — 9 pagine

Risolve due problemi:
  1. La sezione "patrimonio" non era raggiungibile perché il batch lanciava
     solo `dashboard_engine/app.py`, che vede solo le proprie pagine `E*`.
  2. La navigazione lineare E1..E14 era disorientante: qui le pagine sono
     raggruppate per FASE LOGICA dell'analisi (Overview → Asset → Macro →
     Risk & Forecast → Action), così l'utente segue il flusso di ragionamento.

Avvio:
  poetry run streamlit run app_unified.py

Richiede Streamlit >= 1.36 per `st.navigation()` con dict di gruppi.
Le rules 20 (DESIGN_TOKENS), 21 (no cross-import), 32 (auth) restano
soddisfatte: questo file fa solo routing, non logica di business.

Cambiamenti v7.1:
  · Aggiunta pagina E0 — API Health Dashboard (Rules 47-48): semaforo
    sorgenti, override manuali, force refresh.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

# ────────────────────────────────────────────────────────────────────────────
# v7.1.2 hotfix: carica .env PRIMA di qualsiasi altro import che legga env vars.
# Senza questa chiamata, FRED/Alpha Vantage/Finnhub apparivano "no API key"
# anche quando la chiave era presente nel file .env.
# ────────────────────────────────────────────────────────────────────────────
from shared.env_loader import get_api_key_statuses, load_environment

_ENV_REPORT = load_environment()

# ────────────────────────────────────────────────────────────────────────────
# v7.1.3 hotfix B3: applica le migration SQLite all'avvio (idempotente).
# Senza questa chiamata, il DB partiva vuoto e P3/P4/P5/P6 crashavano con
# "no such table: ...". apply_sqlite_migrations() non solleva mai: in caso
# di errore lo registra in _MIGRATIONS_REPORT che mostriamo in sidebar.
# ────────────────────────────────────────────────────────────────────────────
from shared.db.migrations_runner import apply_sqlite_migrations
from shared.db.duckdb_migrator import run_pending_migrations

_MIGRATIONS_REPORT = apply_sqlite_migrations()

# v10.2.0: applica anche le migration DuckDB all'avvio (idempotente).
# Senza questa chiamata, nuove tabelle (consensus_estimates, ecc.) non venivano
# create finché l'utente non le lanciava manualmente, causando errori silenziosi
# nei bottoni "📥 Carica consensus" e simili.
try:
    run_pending_migrations()
except Exception:
    pass  # non-fatal: la UI parte comunque

# Auth gating (Rule 32) — disattivato in dev se STREAMLIT_AUTH_ENABLED=false
try:
    from presentation.ui.auth import require_auth
except ImportError:  # pragma: no cover — fallback se auth non implementata
    def require_auth() -> None:
        return


# ────────────────────────────────────────────────────────────────────────────
# Page config (deve essere la PRIMA chiamata Streamlit)
# ────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MarketAI · Professional Edition",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

require_auth()


# ────────────────────────────────────────────────────────────────────────────
# Helper: registra una pagina solo se il file esiste (resilient routing)
# ────────────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent


def _page(rel_path: str, title: str, icon: str) -> "st.Page | None":
    """Crea st.Page solo se il file esiste, altrimenti restituisce None."""
    full = ROOT / rel_path
    if not full.exists():
        return None
    return st.Page(str(full), title=title, icon=icon)


# ────────────────────────────────────────────────────────────────────────────
# ENGINE — riorganizzato in 5 cluster logici (era E1..E14 piatto)
# ────────────────────────────────────────────────────────────────────────────
ENG = "presentation/dashboard_engine/pages"

# Cluster 1: visione d'insieme — "dove siamo adesso?"
# E0 (API Health) in cima: prima di guardare i mercati l'utente vede lo
# stato delle sorgenti dati e gli override manuali attivi (Rules 47-48 v7.1).
overview_pages = [
    _page(f"{ENG}/E0_API_Health.py",          "API Health",        "📡"),
    _page(f"{ENG}/E1_Market_Overview.py",     "Overview Mercato",  "🌍"),
    _page(f"{ENG}/E10_Delta_Tracker.py",      "Delta Tracker",     "📈"),
    _page(f"{ENG}/E11_Analysis_Pipeline.py",  "Pipeline Status",   "⚙️"),
]

# Cluster 2: asset class — "cosa c'è là fuori?"
asset_pages = [
    _page(f"{ENG}/E2_Equities.py",            "Azioni",            "📊"),
    _page(f"{ENG}/E3_Bonds.py",               "Obbligazioni",      "📉"),
    _page(f"{ENG}/E4_Commodities.py",         "Materie Prime",     "🛢️"),
    _page(f"{ENG}/E5_Forex_Options.py",       "Forex & Opzioni",   "💱"),
]

# Cluster 3: contesto macro & sentiment — "perché si muove?"
context_pages = [
    _page(f"{ENG}/E6_Macro.py",               "Macro (FRED)",      "🏛️"),
    _page(f"{ENG}/E7_Sentiment.py",           "Sentiment",         "🌡️"),
    _page(f"{ENG}/E8_Correlations.py",        "Correlazioni",      "🕸️"),
    _page(f"{ENG}/M3_Labour_Market.py",       "Labour Market",     "👷"),
    _page(f"{ENG}/M5_Economic_Surprise.py",   "Economic Surprise", "⚡"),
]

# Cluster 4: rischio & previsione — "cosa potrebbe succedere?"
risk_pages = [
    _page(f"{ENG}/E9_Forecasting.py",         "Forecasting",       "🔮"),
    _page(f"{ENG}/Q9_Labour_Forecasting.py",  "Labour Forecast",   "🔬"),
    _page(f"{ENG}/Q10_Surprise_Heatmap.py",   "Surprise Heatmap",  "🗺️"),
    _page(f"{ENG}/E12_Backtesting.py",        "Backtesting",       "🧪"),
    _page(f"{ENG}/E13_Stress_Test.py",        "Stress Test",       "⚡"),
]

# Cluster 5: azione — "cosa devo guardare?"
action_pages = [
    _page(f"{ENG}/E14_Alerts.py",             "Alert Mercato",     "🚨"),
]


# ────────────────────────────────────────────────────────────────────────────
# PERSONAL — flusso "dal patrimonio agli obiettivi"
# ────────────────────────────────────────────────────────────────────────────
PER = "presentation/dashboard_personal/pages"

personal_pages = [
    _page(f"{PER}/P1_Overview_Patrimonio.py", "Overview Patrimonio", "💼"),
    _page(f"{PER}/P4_Net_Worth.py",           "Net Worth",           "💰"),
    _page(f"{PER}/P2_Portafoglio_eToro.py",   "Portafoglio eToro",   "📂"),
    _page(f"{PER}/P3_Cash_Flow.py",           "Cash Flow",           "💸"),
    _page(f"{PER}/P5_Goals.py",               "Obiettivi SMART",     "🎯"),
    _page(f"{PER}/P7_Scenari_Ricchezza.py",   "Scenari Ricchezza",   "🔭"),
    _page(f"{PER}/P6_Profilo_Investitore.py", "Profilo Investitore", "🧭"),
    _page(f"{PER}/P8_Fiscale.py",             "Fiscale (IT)",        "🧾"),
    _page(f"{PER}/P9_Alerts_Personali.py",    "Alert Personali",     "🔔"),
]


# ────────────────────────────────────────────────────────────────────────────
# Filtra pagine None (file mancanti) e costruisci la navigazione
# ────────────────────────────────────────────────────────────────────────────
def _clean(pages: list) -> list:
    return [p for p in pages if p is not None]


nav_dict: dict[str, list] = {}

if overview := _clean(overview_pages):
    nav_dict["📊 Engine · Overview"] = overview
if assets := _clean(asset_pages):
    nav_dict["💹 Engine · Asset Class"] = assets
if context := _clean(context_pages):
    nav_dict["🌐 Engine · Contesto"] = context
if risk := _clean(risk_pages):
    nav_dict["⚡ Engine · Rischio & Previsione"] = risk
if action := _clean(action_pages):
    nav_dict["🚨 Engine · Azione"] = action
if personal := _clean(personal_pages):
    nav_dict["💼 Personal · Patrimonio"] = personal


# ────────────────────────────────────────────────────────────────────────────
# Sidebar branding + health bar (se disponibile)
# ────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🧠 MarketAI")
    st.caption("Professional Edition · v7.1.3")
    st.divider()

    # v7.1.3 (B3): se le auto-migrations sono fallite, l'utente deve saperlo
    # subito — molte pagine personali (P3, P4, P5, P6) crashano se le tabelle
    # non sono state create.
    if _MIGRATIONS_REPORT.error is not None:
        st.error(
            f"⚠️ **Migrazioni DB SQLite fallite:** {_MIGRATIONS_REPORT.error}\n\n"
            "Esegui manualmente: `poetry run alembic upgrade head`"
        )
    elif _MIGRATIONS_REPORT.applied:
        st.caption("✅ DB migrations: ok")

    # v7.1.2: diagnostica .env in sidebar — l'utente vede subito se le API
    # key sono caricate, prima ancora di andare in E0.
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

    # Health status (Rule 30) — best-effort, non blocca se non disponibile.
    #
    # Il componente del progetto ha firma `render_health_status_bar(tokens, health)`
    # quindi qui tentiamo di costruire le dipendenze:
    #   · tokens → DESIGN_TOKENS dal theme
    #   · health → HealthChecker(...).check_all()
    #
    # Se una qualsiasi delle dipendenze non è disponibile in questo punto del
    # boot (componenti DB non ancora inizializzati, firme diverse, ecc.) si
    # ripiega silenziosamente su un badge minimale. La barra completa verrà
    # renderizzata dalle singole pagine che già hanno le dipendenze in scope.
    try:
        from presentation.ui.components.health_status_bar import (  # type: ignore
            render_health_status_bar,
        )
        from presentation.ui.theme import DESIGN_TOKENS  # type: ignore
        from shared.health import HealthChecker  # type: ignore

        # HealthChecker richiede client DB + cache. Tentiamo la costruzione
        # tramite i singleton/getter del progetto, se esposti.
        try:
            from shared.db.duckdb_client import DuckDBClient  # type: ignore
            from shared.db.sqlite_client import SQLiteClient  # type: ignore
            from shared.cache import CacheManager  # type: ignore

            health = HealthChecker(
                duckdb_client=DuckDBClient.get(),
                sqlite_client=SQLiteClient.get(),
                cache_manager=CacheManager.get(),
            ).check_all()
            render_health_status_bar(DESIGN_TOKENS, health)
        except (ImportError, AttributeError, TypeError):
            # Dipendenze non recuperabili da qui: badge minimale di fallback.
            st.caption("🟢 Sistema attivo")
    except (ImportError, AttributeError, TypeError):
        # Componente o theme non ancora installati: silenzio.
        pass

# Esegui la pagina selezionata
if not nav_dict:
    st.error(
        "❌ Nessuna pagina trovata. Verifica che la struttura "
        "`presentation/dashboard_engine/pages/` e "
        "`presentation/dashboard_personal/pages/` esista."
    )
    st.stop()

pg = st.navigation(nav_dict, position="sidebar")
pg.run()
