# ruff: noqa: N999
"""E0 — API Health & Data Sources Dashboard (v7.1.1).

Risolve "API che risultano offline" della v7.1.0: ora ogni sorgente viene
PINGATA realmente (HTTP GET con timeout) tramite ``ApiHealthChecker``,
non hardcoded "ℹ️ N/A".

Fornisce:
  - Tabella stato live di Yahoo Finance, FRED, Alpha Vantage, Finnhub.
  - Bottone "Aggiorna ora" che forza re-ping.
  - Gestione override manuali (Rule 43).
  - Form aggiungi-override.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from engine.market_data.hardening.api_health_checker import (
    ApiHealthChecker,
    ApiSourceStatus,
    ApiState,
)
from engine.market_data.live_market_service import get_live_market_service
from personal.data_entry.override_store import ManualOverrideStore
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page
from presentation.ui.session_keys import SK
from shared.env_loader import get_api_key_statuses, load_environment

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.1.2"

__all__ = ["body_api_health"]


def _format_latency(status: ApiSourceStatus) -> str:
    """Formatta latency con fallback per casi senza misurazione."""
    if status.latency_ms is None:
        return "—"
    return f"{status.latency_ms:.0f} ms"


def _render_sources_status(st_module) -> None:  # pragma: no cover -- Streamlit
    """Sezione 1: stato sorgenti dati (live ping).

    Bugfix v7.1.1: prima i provider non-yfinance avevano stato hardcoded
    "ℹ️ N/A". Ora ApiHealthChecker pinga realmente ogni endpoint.
    """
    st = st_module
    render_section_header(
        "📡 Sorgenti dati · Ping Live",
        "Stato real-time delle sorgenti API esterne · click 'Aggiorna ora' per riprovare",
    )

    # Cache risultati ping in session_state per non rifare 4 chiamate
    # HTTP a ogni rerender (ad es. quando l'utente modifica un override).
    if SK.API_HEALTH_RESULTS not in st.session_state:
        st.session_state[SK.API_HEALTH_RESULTS] = None

    cols = st.columns([1, 1, 3])
    with cols[0]:
        if st.button(
            "🔄 Aggiorna stato API",
            type="primary",
            use_container_width=True,
            help="Pinga di nuovo Yahoo, FRED, Alpha Vantage, Finnhub.",
            key="refresh_api_health",
        ):
            with st.spinner("Ping in corso..."):
                checker = ApiHealthChecker(timeout=5.0)
                st.session_state[SK.API_HEALTH_RESULTS] = checker.check_all()
            st.rerun()

    # Primo accesso: ping automatico
    if st.session_state[SK.API_HEALTH_RESULTS] is None:
        with st.spinner("Verifica stato sorgenti API..."):
            checker = ApiHealthChecker(timeout=5.0)
            st.session_state[SK.API_HEALTH_RESULTS] = checker.check_all()

    statuses: list[ApiSourceStatus] = st.session_state[SK.API_HEALTH_RESULTS]

    # Aggiungi anche Yahoo Finance via LiveMarketService cache (per coerenza
    # con altre pagine: stato del fetch reale dei KPI, non solo ping).
    svc = get_live_market_service()
    snapshot = svc.get_kpi_snapshot()
    yf_kpis_ok = sum(1 for k in snapshot.kpis if k.value is not None)
    yf_kpis_total = len(snapshot.kpis)

    rows = []
    for status in statuses:
        # Aggiungiamo info KPI per Yahoo
        extra_note = status.message
        if status.name == "Yahoo Finance":
            extra_note = (
                f"{status.message} · "
                f"KPI mercato fetchati: {yf_kpis_ok}/{yf_kpis_total} "
                f"(ultimo: {snapshot.fetched_at_human})"
            )
        rows.append(
            {
                "Sorgente": status.name,
                "Stato": status.state_label,
                "Latenza": _format_latency(status),
                "API Key": "✅" if status.has_api_key else "❌",
                "Note": extra_note,
            }
        )

    st.dataframe(rows, use_container_width=True, hide_index=True)

    # Riepilogo aggregato
    n_online = sum(1 for s in statuses if s.state == ApiState.ONLINE)
    n_offline = sum(1 for s in statuses if s.state == ApiState.OFFLINE)
    n_no_key = sum(1 for s in statuses if s.state == ApiState.NO_API_KEY)
    n_degraded = sum(1 for s in statuses if s.state == ApiState.DEGRADED)

    if n_online == len(statuses):
        st.success(f"✅ Tutte le {len(statuses)} sorgenti API rispondono correttamente.")
    elif n_offline > 0:
        st.error(
            f"❌ {n_offline} sorgenti offline — verifica connessione internet "
            f"o stato del provider."
        )
    elif n_degraded > 0:
        st.warning(
            f"⚠️ {n_degraded} sorgenti in stato degradato — possibile rate limit."
        )
    if n_no_key > 0:
        st.info(
            f"🔑 {n_no_key} sorgenti senza API key. "
            f"Aggiungi le chiavi in `.env` per abilitarle."
        )

    # Force refresh KPI mercato (separato dal ping API)
    st.divider()
    cols_kpi = st.columns([1, 3])
    with cols_kpi[0]:
        if st.button(
            "🔄 Force refresh KPI mercato",
            type="secondary",
            use_container_width=True,
            help="Forza un nuovo fetch dei prezzi ignorando la cache TTL",
        ):
            svc.refresh_now()
            st.success("✅ Cache KPI invalidata e ri-fetchati.")
            st.rerun()
    with cols_kpi[1]:
        st.caption(
            f"Cache TTL: 60s · Eta' attuale: {svc.cache_age_seconds():.0f}s · "
            f"KPI live: {yf_kpis_ok}/{yf_kpis_total}"
        )


def _render_active_overrides(st_module) -> None:  # pragma: no cover -- Streamlit
    """Sezione 2: override manuali attivi (Rule 43)."""
    st = st_module
    render_section_header(
        "✏️ Override manuali attivi",
        "Valori utente che sovrascrivono le risposte API (Rule 43)",
    )
    store = ManualOverrideStore()
    overrides = store.list_active()
    if not overrides:
        st.info(
            "Nessun override attivo. "
            "Gli override permettono di correggere manualmente valori errati "
            "restituiti dalle API. Esempio: se yfinance ritorna un prezzo "
            "evidentemente sbagliato, puoi inserire il valore corretto qui "
            "e il sistema lo userà per tutti i calcoli a valle."
        )
        return

    rows = [
        {
            "Tipo": ov.entity_type,
            "Entita'": ov.entity_key,
            "Valore API originale": (
                f"{ov.api_value:.4f}" if ov.api_value is not None else "—"
            ),
            "Valore utente": f"{ov.user_value:.4f}",
            "Nota": ov.note,
            "Creato il": ov.created_at.strftime("%Y-%m-%d %H:%M"),
        }
        for ov in overrides
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    labels = [
        f"{ov.entity_type}::{ov.entity_key} (utente: {ov.user_value:.2f})"
        for ov in overrides
    ]
    selected = st.selectbox(
        "Rimuovi un override (ripristina valore API)",
        options=["—"] + labels,
        key="override_remover",
    )
    if selected != "—":
        idx = labels.index(selected)
        ov = overrides[idx]
        if st.button(
            f"🗑️ Rimuovi override {ov.entity_key}",
            type="secondary",
        ):
            store.remove(ov.entity_type, ov.entity_key)
            st.success(f"Override su {ov.entity_key} rimosso.")
            st.rerun()


def _render_add_override_form(st_module) -> None:  # pragma: no cover -- Streamlit
    """Sezione 3: form per aggiungere un nuovo override."""
    st = st_module
    render_section_header(
        "➕ Aggiungi override",
        "Inserisci un valore manuale per sovrascrivere quello restituito dall'API",
    )

    with st.form("add_override_form"):
        cols = st.columns(2)
        with cols[0]:
            entity_type = st.selectbox(
                "Tipo di valore",
                options=[
                    "price",
                    "pe_ratio",
                    "market_cap",
                    "eps",
                    "dividend_yield",
                    "altro",
                ],
                help="Categoria del valore che vuoi sovrascrivere.",
            )
            entity_key = st.text_input(
                "Identificatore *",
                placeholder="Es. AAPL, S&P 500, EURUSD",
                help="Ticker o termine glossario per cui applicare l'override.",
            )
        with cols[1]:
            api_value = st.number_input(
                "Valore API originale (opzionale, per memoria)",
                value=0.0,
                step=0.01,
                format="%.4f",
            )
            user_value = st.number_input(
                "Valore corretto (utente) *",
                value=0.0,
                step=0.01,
                format="%.4f",
            )
        note = st.text_area(
            "Nota",
            placeholder="Es. 'AV ha rate-limited, valore preso da Bloomberg'",
            max_chars=500,
        )
        submitted = st.form_submit_button("💾 Salva override", type="primary")

    if not submitted:
        return
    if not entity_key.strip():
        st.error("❌ Inserisci un identificatore.")
        return
    if user_value == 0.0:
        st.warning("⚠️ Il valore utente e' 0. Sicuro che e' corretto?")

    store = ManualOverrideStore()
    store.set(
        entity_type=entity_type,
        entity_key=entity_key.strip().upper(),
        user_value=user_value,
        api_value=api_value if api_value != 0.0 else None,
        note=note,
    )
    st.success(
        f"✅ Override salvato per {entity_key}: "
        f"API={api_value:.4f} -> User={user_value:.4f}."
    )
    st.rerun()


def _render_env_status(st_module) -> None:  # pragma: no cover -- Streamlit
    """Sezione: stato del file .env e API keys configurate (v7.1.2).

    Risolve il bug 'API risultano offline anche con .env valido': mostra
    direttamente quale .env e' stato caricato e quali key risultano
    'configurate', 'placeholder' o 'mancanti'.
    """
    st = st_module
    render_section_header(
        "🗂️ Stato file .env",
        "Verifica che il file di configurazione sia stato caricato correttamente",
    )

    # Re-load defensivo: lo stato puo' essere ricontrollato anche dopo che
    # l'utente ha modificato il .env e premuto Aggiorna in altra pagina.
    report = load_environment()

    if not report.loaded_successfully:
        st.error(
            "❌ **Nessun file `.env` trovato.** "
            "Le API esterne saranno disabilitate. "
            "Crea il file con: `cp .env.example .env` e riempi le chiavi."
        )
        with st.expander("Percorsi cercati", expanded=False):
            for p in report.candidates_tried:
                st.code(str(p), language="bash")
        return

    st.success(
        f"✅ File caricato: `{report.dotenv_path}` "
        f"({report.loaded_count} variabili)"
    )

    statuses = get_api_key_statuses()
    rows = []
    for s in statuses:
        if s.is_usable:
            stato = "✅ Configurata"
        elif s.is_placeholder:
            stato = "⚠️ Placeholder (modifica il valore in .env)"
        elif s.is_set:
            stato = "⚠️ Vuota"
        else:
            stato = "🔑 Non configurata"
        rows.append(
            {
                "API": s.name,
                "Variabile env": s.env_var,
                "Stato": stato,
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)


def body_api_health(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

    _render_env_status(st)
    st.divider()
    _render_sources_status(st)
    st.divider()
    _render_active_overrides(st)
    st.divider()
    _render_add_override_form(st)


if __name__ == "__main__":  # pragma: no cover
    render_page("API Health", "📡", body_api_health)
