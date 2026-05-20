"""Chiavi session_state Streamlit come costanti tipizzate.

Elimina le stringhe literal sparse nelle pagine (P7 — ROADMAP_CODE_QUALITY_v1.0).
Un typo su una chiave literal introduce bug silenziosi (chiave non trovata →
stato vuoto senza errore). Usando SK.* il type-checker e l'IDE segnalano errori.

Uso::

    from presentation.ui.session_keys import SK

    result = st.session_state.get(SK.ETORO_IMPORT_RESULT_API)
    st.session_state[SK.FORCE_REFRESH] = True
"""
from __future__ import annotations


class _SessionKeys:
    """Namespace per le chiavi session_state. Non istanziare: usa SK."""

    # ── Auth ───────────────────────────────────────────────────────────────
    AUTHENTICATED            = "authenticated"
    SHOW_QUESTIONNAIRE       = "show_questionnaire"
    ACTIVE_PAGE              = "active_page"

    # ── P2 — Portafoglio eToro ─────────────────────────────────────────────
    ETORO_IMPORT_RESULT_API  = "etoro_import_result_api"
    ETORO_IMPORT_RESULT_XLSX = "etoro_import_result_xlsx"

    # ── E1 — Market Overview ───────────────────────────────────────────────
    FORCE_REFRESH            = "force_refresh"
    CLEAR_CACHE              = "clear_cache"

    # ── E4/E5 — Commodities / Forex ────────────────────────────────────────
    COMMODITY_FORCE_REFRESH  = "commodity_force_refresh"

    # ── T2 — Stress Test ──────────────────────────────────────────────────
    T2_RESULTS               = "t2_results"
    T2_COMPARE               = "t2_compare"
    T2_TICKER                = "t2_ticker"

    # ── K1 — Markets / Rebalancing ────────────────────────────────────────
    LAST_REBALANCING_REPORT  = "last_rebalancing_report"

    # ── Diagnostics ────────────────────────────────────────────────────────
    API_HEALTH_RESULTS       = "api_health_results"

    # ── Auth (Rule 32) ─────────────────────────────────────────────────────
    AUTH_TOKEN               = "auth_token"

    # ── Sidebar navigation ─────────────────────────────────────────────────
    SIDEBAR_SEARCH           = "sidebar_search"
    SIDEBAR_EXPANDED_PREFIX  = "sidebar_expanded_"   # + group.id

    # ── Analytics results ─────────────────────────────────────────────────
    BACKTEST_RESULT          = "backtest_result"


SK = _SessionKeys()
