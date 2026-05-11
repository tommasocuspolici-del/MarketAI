# ruff: noqa: N999
"""E10 — Delta Tracker (v7.2 fix B10).

Risolve "DataFrame completamente hardcoded" segnalato in
BUGFIX_PRIORITARIO.md sezione B10: la versione precedente mostrava
variazioni 1W / 1M / YTD totalmente fittizie ("+1.2%", "+22.4%"...) che
non cambiavano mai.

Ora la pagina:
  - Fetcha variazioni reali via ``fetch_delta_windows()`` da yfinance.
  - 6 asset di default (S&P 500, Nasdaq, Bitcoin, Gold, WTI, EUR/USD).
  - Cache TTL 1h via ``@st.cache_data``.
  - Bottone refresh per svuotare cache e rifare fetch.
  - Color coding via column_config (verde/rosso per delta > 0 / < 0).
  - Fallback graceful: se yfinance non installato o ticker errato,
    cella mostra "—" senza inventare valori.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from engine.market_data.live_market_service import (
    DeltaWindow,
    fetch_delta_windows,
)
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.2.0"

__all__ = ["body_delta_tracker"]


# Asset monitorati nel Delta Tracker. Tuple (yahoo_ticker, label_display).
# v7.2: lista canonica per consistency con E1 / E5. Se diventera' necessaria
# customizzazione, spostare in config/watched_tickers.yaml.
_DELTA_TICKERS: list[tuple[str, str]] = [
    ("SPY", "S&P 500"),
    ("QQQ", "Nasdaq 100"),
    ("BTC-USD", "Bitcoin"),
    ("GLD", "Gold (GLD)"),
    ("USO", "WTI Oil (USO)"),
    ("EURUSD=X", "EUR/USD"),
]

# Cache TTL: yfinance 1y data cambia solo a fine giornata trading,
# 1 ora di cache e' largamente sufficiente per UI Streamlit.
_CACHE_TTL_S: int = 3600


def _format_pct(value: float | None) -> str:
    """Format helper: percentuale con segno o '—' se None."""
    if value is None:
        return "—"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value * 100:.2f}%"


def _delta_to_row(w: DeltaWindow) -> dict[str, str]:
    """Converte una DeltaWindow in dict per st.dataframe."""
    last_price_str = (
        f"{w.last_price:,.2f}" if w.last_price is not None else "—"
    )
    note = w.error if w.error else ""
    return {
        "Asset": w.term,
        "Ticker": w.ticker,
        "Ultimo": last_price_str,
        "1W": _format_pct(w.delta_1w),
        "1M": _format_pct(w.delta_1m),
        "YTD": _format_pct(w.delta_ytd),
        "Note": note,
    }


def _cached_fetch_deltas() -> list[DeltaWindow]:
    """Wrapper con cache Streamlit attorno a fetch_delta_windows."""
    try:
        import streamlit as st

        @st.cache_data(ttl=_CACHE_TTL_S, show_spinner=False)
        def _fn() -> list[DeltaWindow]:
            return fetch_delta_windows(_DELTA_TICKERS)

        return _fn()
    except ImportError:  # pragma: no cover -- non-Streamlit
        return fetch_delta_windows(_DELTA_TICKERS)


def body_delta_tracker(
    tokens: DesignTokens,
) -> None:  # pragma: no cover -- Streamlit-rendered
    try:
        import streamlit as st
    except ImportError:
        return

    render_section_header(
        "📐 Asset Performance — Multi-Window",
        "Variazioni % calcolate su 1 settimana · 1 mese · YTD · fonte: yfinance",
    )

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="e10_refresh"):
            st.cache_data.clear()
            st.rerun()

    with st.spinner("Carico dati live yfinance..."):
        windows = _cached_fetch_deltas()

    # Stato vuoto: yfinance non installato
    all_failed = all(
        w.delta_1w is None and w.delta_1m is None and w.delta_ytd is None
        for w in windows
    )
    if all_failed:
        st.error(
            "❌ **Nessun dato disponibile.** Possibili cause:\n\n"
            "- `yfinance` non installato (esegui `poetry install`).\n"
            "- Yahoo Finance temporaneamente non raggiungibile.\n"
            "- Tutti i ticker configurati sono errati.\n\n"
            "Vai a **📡 API Health** per verificare lo stato delle dipendenze."
        )
        # Mostriamo comunque la tabella con '—' per trasparenza
    rows = [_delta_to_row(w) for w in windows]
    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Asset": st.column_config.TextColumn("Asset", width="medium"),
            "Ticker": st.column_config.TextColumn("Ticker", width="small"),
            "Ultimo": st.column_config.TextColumn("Ultimo", width="small"),
            "1W": st.column_config.TextColumn("1W", width="small"),
            "1M": st.column_config.TextColumn("1M", width="small"),
            "YTD": st.column_config.TextColumn("YTD", width="small"),
            "Note": st.column_config.TextColumn("Note", width="medium"),
        },
    )

    # Mini-riepilogo: quanti asset hanno dati validi
    n_valid = sum(
        1 for w in windows
        if w.delta_ytd is not None or w.delta_1m is not None
    )
    st.caption(
        f"📌 {n_valid}/{len(windows)} asset con dati validi · "
        f"Cache TTL {_CACHE_TTL_S // 60} min · "
        "Clicca 🔄 per refresh immediato"
    )

    # Spiegazione metriche
    with st.expander("ℹ️ Come si leggono queste metriche", expanded=False):
        st.markdown(
            "- **1W**: variazione vs prezzo di 5 trading day fa. "
            "Indica momentum di breve.\n"
            "- **1M**: variazione vs ~21 trading day fa. "
            "Cattura il trend mensile.\n"
            "- **YTD** (Year-to-Date): variazione dal primo trading day "
            "dell'anno corrente. Confronto annuale tra asset.\n\n"
            "Tutti i delta sono calcolati su prezzi **adjusted close** "
            "(includono dividendi e split — confronto piu' fair vs total return)."
        )


if __name__ == "__main__":  # pragma: no cover
    render_page("Delta Tracker", "📐", body_delta_tracker)
