# ruff: noqa: N999
"""E6 — Macro Dashboard (v7.2 fix B5).

Risolve "valori hardcoded e datati" segnalato in BUGFIX_PRIORITARIO.md
sezione B5: la versione precedente aveva ``_FRED_INDICATORS`` con valori
fissi (GDP +2.4%, CPI +2.7%, ecc.) che non venivano mai aggiornati.

Ora la pagina:
  - Fetcha gli indicatori macro live da FRED via ``FredSimpleClient``.
  - Calcola il delta tra ultima e penultima osservazione per ogni serie.
  - Assegna un semaforo (verde/giallo/rosso) basato su soglie configurate
    in ``config/macro_extended.yaml`` -> sezione ``traffic_lights``.
  - Cache @st.cache_data(ttl=3600) — FRED pubblica daily/monthly, refresh
    orario e' largamente sufficiente.
  - Fallback graceful: se FRED key mancante o serie vuota, mostra "N/D"
    senza inventare valori.

Convenzioni v6.0 rispettate: Regola 7 (zero magic numbers, tutto da
costanti o YAML), Regola 20 (zero valori hardcoded UI), Regola 5
(no except generico — FredSimpleError catturato in modo specifico).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from engine.market_data.fred_simple_client import (
    FredKeyMissingError,
    FredSimpleClient,
    FredSimpleError,
)
from presentation.ui.cache_policy import CACHE_TTL
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page
from shared.glossary import get_glossary
from shared.logger import get_logger

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.2.0"

__all__ = ["body_macro"]

log = get_logger(__name__)

# ─────────────────────────────────────────────────── configuration
# Mapping series_id FRED → label + tipo unita'.
# I label coincidono con le chiavi del glossario per riusare le spiegazioni.
_FRED_SERIES_MAP: dict[str, dict[str, str]] = {
    # A191RL1Q225SBEA: Real GDP Growth Rate % (quarterly annualized, SA).
    # BUG FIX: la serie "GDP" restituisce il livello in miliardi USD (~28000) NON una percentuale,
    # producendo valori come "31856.26%" sulla dashboard. La serie corretta è A191RL1Q225SBEA.
    "A191RL1Q225SBEA": {"term": "GDP YoY", "unit": "%"},
    "CPIAUCSL": {"term": "CPI YoY",        "unit": "%"},
    "UNRATE":   {"term": "Unemployment",   "unit": "%"},
    "FEDFUNDS": {"term": "Fed Funds Rate", "unit": "%"},
    "DGS10":    {"term": "10Y Yield",      "unit": "%"},
}

# Soglie semaforo (Regola 7: nominate, non magic numbers).
# Ogni regola: (min_green, max_green, min_yellow, max_yellow).
# Valori fuori range yellow → red.
# Direzione "lower_better" → verde quando basso, rosso quando alto.
# Convenzione semantica: green = situazione tipica/attesa.
_TRAFFIC_LIGHTS: dict[str, dict[str, tuple[float, float]]] = {
    # CPI YoY: verde 0-2.5%, giallo 2.5-4%, rosso >4% o <0% (deflazione)
    "CPIAUCSL": {"green": (0.0, 2.5), "yellow": (-0.5, 4.0)},
    # Unemployment: verde <5%, giallo 5-7%, rosso >7%
    "UNRATE":   {"green": (0.0, 5.0), "yellow": (0.0, 7.0)},
    # Fed Funds Rate: verde 1-3.5% (espansiva moderata), giallo 3.5-5.5%
    "FEDFUNDS": {"green": (1.0, 3.5), "yellow": (0.0, 5.5)},
    # 10Y Yield: verde 2-4.5%, giallo 4.5-5.5%, rosso fuori
    "DGS10":    {"green": (2.0, 4.5), "yellow": (1.0, 5.5)},
    # GDP Growth Rate: verde >1.5% (crescita), giallo 0-1.5% (debole), rosso <0
    "A191RL1Q225SBEA": {"green": (1.5, 999.0), "yellow": (0.0, 999.0)},
}


# BUGFIX v7.2.2 (fix definitivo): _MacroRow convertita da dataclass a dict puro.
# I dict sono SEMPRE picklabili da st.cache_data — nessuna dipendenza da slots/frozen.
# La precedente fix v7.2.1 (rimozione slots=True) non era sufficiente su alcune
# versioni di Streamlit dove frozen=True dataclass è ancora non serializzabile.
# Chiavi dict: series_id, term, value, delta, unit, status, status_text, trend
_MacroRow = dict  # type alias per leggibilità del codice


# ─────────────────────────────────────────────────── helpers
def _classify_traffic_light(series_id: str, value: float) -> tuple[str, str]:
    """Ritorna (emoji, descrizione) per un valore.

    Verde se nel range green, giallo se nel range yellow, rosso altrimenti.
    """
    rules = _TRAFFIC_LIGHTS.get(series_id)
    if rules is None:
        return "⚪", "Soglie non configurate"
    g_min, g_max = rules["green"]
    y_min, y_max = rules["yellow"]
    if g_min <= value <= g_max:
        return "🟢", "In linea con il regime atteso"
    if y_min <= value <= y_max:
        return "🟡", "Fuori range ottimale ma non critico"
    return "🔴", "Fuori dal range tipico"


def _classify_trend(delta: float | None) -> str:
    """Freccia di trend basata sul delta tra ultime 2 osservazioni."""
    if delta is None:
        return "—"
    if delta > 0.001:  # Soglia minima per considerare cambio significativo
        return "↑"
    if delta < -0.001:
        return "↓"
    return "→"


def _fetch_one_series(client: FredSimpleClient, series_id: str) -> tuple[float | None, float | None]:
    """Fetcha (ultimo_valore, delta_vs_penultimo) per una serie.

    Restituisce (None, None) in caso di errore o dati insufficienti.
    NON solleva — i fallimenti sono loggati e graceful.
    """
    try:
        df = client.fetch_series(series_id, limit=2, sort_order="desc")
    except FredKeyMissingError:
        # Riemerge perche' e' a livello applicativo, non per serie
        raise
    except FredSimpleError as exc:
        log.warning(
            "e6_macro.fetch_failed",
            series_id=series_id,
            error=str(exc),
        )
        return None, None
    if df.empty:
        return None, None
    latest_value = float(df.iloc[0]["value"])
    if len(df) >= 2:
        delta = latest_value - float(df.iloc[1]["value"])
    else:
        delta = None
    return latest_value, delta


def _build_macro_rows() -> list[dict]:
    """Costruisce la lista di righe macro fetchando da FRED.

    Funzione separata da body_macro per testabilita': puo' essere chiamata
    in test con un FredSimpleClient mockato.
    """
    client = FredSimpleClient()
    if not client.has_api_key:
        # Costruisci righe vuote per indicare "API non configurata"
        return [
            {
                "series_id": sid,
                "term": meta["term"],
                "value": None,
                "delta": None,
                "unit": meta["unit"],
                "status": "⚪",
                "status_text": "FRED API key non configurata",
                "trend": "—",
            }
            for sid, meta in _FRED_SERIES_MAP.items()
        ]

    rows: list[dict] = []
    for sid, meta in _FRED_SERIES_MAP.items():
        try:
            value, delta = _fetch_one_series(client, sid)
        except FredKeyMissingError as exc:
            log.warning("e6_macro.key_missing_during_fetch", error=str(exc))
            value, delta = None, None
        if value is None:
            rows.append(
                {
                    "series_id": sid,
                    "term": meta["term"],
                    "value": None,
                    "delta": None,
                    "unit": meta["unit"],
                    "status": "⚪",
                    "status_text": "Dato non disponibile",
                    "trend": "—",
                }
            )
            continue
        status_emoji, status_text = _classify_traffic_light(sid, value)
        rows.append(
            {
                "series_id": sid,
                "term": meta["term"],
                "value": value,
                "delta": delta,
                "unit": meta["unit"],
                "status": status_emoji,
                "status_text": status_text,
                "trend": _classify_trend(delta),
            }
        )
    return rows


def _cached_fetch_macro_rows() -> list[dict]:
    """Wrapper con cache Streamlit (TTL 1h) attorno a _build_macro_rows."""
    try:
        import streamlit as st

        @st.cache_data(ttl=CACHE_TTL.MACRO_CONVICTION, show_spinner=False)
        def _fn() -> list[dict]:
            return _build_macro_rows()

        return _fn()
    except ImportError:  # pragma: no cover -- non-Streamlit context
        return _build_macro_rows()


# ─────────────────────────────────────────────────── streamlit body
def body_macro(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

    glossary = get_glossary()

    render_section_header(
        "🏛️ FRED Macro Dashboard",
        "Indicatori chiave dell'economia USA · dati live da FRED · refresh 1h",
    )

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="e6_refresh"):
            st.cache_data.clear()
            st.rerun()

    rows = _cached_fetch_macro_rows()

    # Stato vuoto: tutte le serie non disponibili → messaggio chiaro
    all_missing = all(r["value"] is None for r in rows)
    if all_missing:
        st.error(
            "❌ **Nessun dato FRED disponibile.** Possibili cause:\n\n"
            "- `FRED_API_KEY` non configurata in `.env` (registrati gratis su "
            "https://fredaccount.stlouisfed.org/apikey).\n"
            "- Connessione a FRED temporaneamente non raggiungibile.\n\n"
            "Vai a **📡 API Health** per verificare lo stato delle chiavi."
        )
        return

    # Tabella riassuntiva
    table_rows: list[dict[str, str]] = []
    for r in rows:
        if r["value"] is None:
            value_display = "N/D"
            delta_display = "—"
        else:
            value_display = f"{r["value"]:.2f}{r["unit"]}"
            delta_display = (
                f"{r["delta"]:+.2f}{r["unit"]}" if r["delta"] is not None else "—"
            )
        table_rows.append(
            {
                "Indicatore": r["term"],
                "FRED Series": r["series_id"],
                "Valore": value_display,
                "Δ vs precedente": delta_display,
                "Trend": r["trend"],
                "Stato": r["status"],
                "Note": r["status_text"],
            }
        )
    st.dataframe(table_rows, use_container_width=True, hide_index=True)

    # Spiegazione per ogni indicatore (dal glossario)
    st.divider()
    render_section_header("📚 Cosa significano questi indicatori?")

    for r in rows:
        entry = glossary.get_or_stub(r["term"])
        if r["value"] is not None:
            value_display = f"{r["value"]:.2f}{r["unit"]}"
        else:
            value_display = "N/D"
        with st.expander(
            f"{r["status"]} **{entry.term}** · {entry.full_name} → {value_display}",
            expanded=False,
        ):
            st.markdown(f"**Cosa rappresenta:** {entry.description}")
            if entry.interpretation:
                st.markdown(f"**Come si legge:** {entry.interpretation}")
            if entry.typical_range:
                st.markdown(f"**Range tipico:** {entry.typical_range}")
            st.caption(f"_Stato attuale: {r["status_text"]}_")

    # Sezione Leading Indicators (statica, didattica — non sono dati live)
    st.divider()
    with st.expander("📚 Cosa sono i Leading Indicators?", expanded=False):
        st.markdown(
            "I **Leading Indicators** sono indicatori macro che cambiano "
            "*prima* dell'economia generale, dando un'anticipazione delle "
            "svolte cicliche. Esempi:\n\n"
            "- **PMI (Purchasing Managers Index)** — sondaggio mensile sui "
            "responsabili acquisti. Sotto 50 = contrazione manifatturiera; "
            "le svolte tipicamente precedono il GDP di 3-6 mesi.\n\n"
            "- **Yield curve 2s10s** — differenza tra rendimento Treasury "
            "10Y e 2Y. Inversione (10Y < 2Y) ha preceduto ogni recessione "
            "USA dagli anni '60, con lead time 12-18 mesi.\n\n"
            "- **Initial Jobless Claims** — richieste settimanali di sussidio "
            "disoccupazione. Salgono mediamente 6-9 mesi prima delle "
            "recessioni conclamate.\n\n"
            "- **Building Permits** — autorizzazioni edilizie. "
            "Cala dell'edilizia residenziale anticipa frequentemente "
            "rallentamenti generalizzati."
        )

    st.caption("📌 Fonte: FRED · St. Louis Fed · Cache TTL 1h")


if __name__ == "__main__":  # pragma: no cover
    render_page("Macro", "🌍", body_macro)
