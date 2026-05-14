# ruff: noqa: N999
"""E2 — Equities (v7.1.2 hotfix).

Risolve "candele e volumi statici per ogni asset" segnalato in
ULTERIORI_ERRORI.txt: la versione precedente usava ``build_mock_ohlcv()``
con ``np.random.default_rng(42)`` (sempre lo stesso seed -> grafico
identico a ogni reload).

Ora la pagina:
  - Fetcha OHLCV reale via yfinance per il ticker selezionato.
  - Cache @st.cache_data(ttl=300) per evitare HTTP storm su rerender.
  - Fallback graceful se yfinance non e' installato o se il fetch fallisce
    (mostra messaggio chiaro invece di candele finte).
  - Volume e prezzo cambiano davvero quando l'utente cambia ticker.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from presentation.ui.components.candlestick_pro import render_candlestick_pro
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.1.2"

__all__ = ["body_equities", "fetch_ohlcv_yfinance"]

# Universo iniziale — equity USA piu' liquide. L'utente puo' inserire
# ticker custom nel campo testuale.
_DEFAULT_TICKERS: tuple[str, ...] = (
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "NVDA",
    "TSLA",
    "BRK-B",
    "JPM",
    "V",
)

_PERIOD_OPTIONS: dict[str, str] = {
    "1 mese": "1mo",
    "3 mesi": "3mo",
    "6 mesi": "6mo",
    "1 anno": "1y",
    "2 anni": "2y",
    "5 anni": "5y",
}


def fetch_ohlcv_yfinance(ticker: str, period: str = "1y") -> pd.DataFrame:
    """Fetch OHLCV reale da Yahoo Finance.

    Args:
        ticker: Symbol Yahoo (es. 'AAPL', 'MSFT', '^GSPC').
        period: Periodo yfinance ('1mo', '3mo', '6mo', '1y', '2y', '5y').

    Returns:
        DataFrame con colonne ts, open, high, low, close, volume.
        DataFrame vuoto se fetch fallisce o yfinance non e' installato.
    """
    try:
        import yfinance as yf
    except ImportError:
        return pd.DataFrame()

    try:
        # auto_adjust=False perche' i grafici candlestick mostrano l'open
        # storico non aggiustato. Per i ratio fondamentali useremo close adj.
        df = yf.download(
            tickers=ticker,
            period=period,
            interval="1d",
            progress=False,
            auto_adjust=False,
            threads=False,
            group_by="column",
        )
    except (OSError, ValueError, KeyError):
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    # yfinance ritorna MultiIndex se piu' ticker o single-level se uno solo.
    # Normalizziamo a single-level lowercase.
    if isinstance(df.columns, pd.MultiIndex):
        # Prendiamo il primo livello (open/high/...) ignorando il ticker
        df.columns = df.columns.get_level_values(0)

    df = df.rename(columns=str.lower)
    out = pd.DataFrame(
        {
            "ts": df.index,
            "open": df["open"].astype(float),
            "high": df["high"].astype(float),
            "low": df["low"].astype(float),
            "close": df["close"].astype(float),
            "volume": df["volume"].fillna(0).astype("int64"),
        }
    ).reset_index(drop=True)
    return out


def _cached_fetch(ticker: str, period: str) -> pd.DataFrame:
    """Wrapper con cache Streamlit (TTL 5 min)."""
    try:
        import streamlit as st

        @st.cache_data(ttl=300, show_spinner=False)
        def _fn(t: str, p: str) -> pd.DataFrame:
            return fetch_ohlcv_yfinance(t, p)

        return _fn(ticker, period)
    except ImportError:  # pragma: no cover
        return fetch_ohlcv_yfinance(ticker, period)


def body_equities(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

    render_section_header(
        "📊 Equity Screener",
        "Analisi tecnica con dati reali da Yahoo Finance",
    )

    cols = st.columns([2, 2, 2, 1])
    with cols[0]:
        ticker_select = st.selectbox(
            "Ticker (predefiniti)",
            options=_DEFAULT_TICKERS,
            index=0,
            key="e2_ticker_select",
        )
    with cols[1]:
        custom_ticker = st.text_input(
            "...o ticker custom",
            placeholder="Es. NFLX, ENI.MI, ^GSPC",
            key="e2_custom_ticker",
        ).strip().upper()
    with cols[2]:
        period_label = st.selectbox(
            "Periodo",
            options=list(_PERIOD_OPTIONS.keys()),
            index=3,  # 1 anno
            key="e2_period",
        )
    with cols[3]:
        st.write("")
        st.write("")
        force_refresh = st.button("🔄 Aggiorna", key="e2_refresh")

    ticker = custom_ticker if custom_ticker else ticker_select
    period = _PERIOD_OPTIONS[period_label]

    if force_refresh:
        # Pulisce la cache di Streamlit per questo fetch
        st.cache_data.clear()

    with st.spinner(f"Carico dati {ticker} ({period_label})..."):
        df = _cached_fetch(ticker, period)

    if df.empty:
        st.error(
            f"❌ **Nessun dato OHLCV per `{ticker}`.** Possibili cause:\n\n"
            "- Ticker errato o delisted (verifica il symbol su finance.yahoo.com).\n"
            "- `yfinance` non installato in questo ambiente "
            "(esegui `poetry install` o `pip install yfinance`).\n"
            "- Yahoo Finance momentaneamente non raggiungibile.\n\n"
            "Vai alla pagina **📡 API Health** per verificare lo stato."
        )
        return

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last
    delta_pct = (
        ((last["close"] - prev["close"]) / prev["close"]) * 100.0
        if prev["close"] != 0
        else 0.0
    )
    avg_volume = float(df["volume"].mean())

    cols_kpi = st.columns(4)
    cols_kpi[0].metric(
        "Ultimo close",
        f"{last['close']:,.2f}",
        f"{delta_pct:+.2f}%",
    )
    cols_kpi[1].metric("High periodo", f"{df['high'].max():,.2f}")
    cols_kpi[2].metric("Low periodo", f"{df['low'].min():,.2f}")
    cols_kpi[3].metric("Volume medio", f"{avg_volume:,.0f}")

    render_candlestick_pro(
        tokens,
        df,
        title=f"{ticker} · OHLCV daily ({period_label})",
    )

    st.caption(
        f"📌 Fonte: Yahoo Finance · {len(df)} barre giornaliere · "
        f"Cache TTL 5 min · ultimo dato: {last['ts'].date() if hasattr(last['ts'], 'date') else last['ts']}"
    )


if __name__ == "__main__":  # pragma: no cover
    render_page("Equities", "📈", body_equities)
