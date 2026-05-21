# ruff: noqa: N999
"""Q12 — Multi-Timeframe Analysis (Blocco D).

SignalBadge per ogni timeframe · confluence score · pattern _load_*() pure.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from presentation.ui.cache_policy import CACHE_TTL
from presentation.ui.components import EmptyState, SignalBadge
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "1.0.0"
__all__ = ["body_multi_timeframe"]

_TIMEFRAME_LABELS = {
    "daily":   "Giornaliero (D)",
    "weekly":  "Settimanale (W)",
    "monthly": "Mensile (M)",
}


def _load_mtf_signal(ticker: str) -> dict:
    try:
        from engine.analytics.technical.multi_timeframe_analyzer import MultiTimeframeAnalyzer
        from shared.db.duckdb_client import get_duckdb_client
        from shared.db.prices_repo import PricesRepository

        db = get_duckdb_client()
        repo = PricesRepository(db)
        ohlcv = repo.read_ohlcv(ticker, limit=504)  # ~2 anni
        if ohlcv.empty:
            return {}
        analyzer = MultiTimeframeAnalyzer(publish_to_bus=False)
        result = analyzer.analyze(ohlcv, ticker=ticker)
        return {
            "confluence":   result.confluence,
            "conviction":   result.conviction,
            "n_agreeing":   result.n_agreeing,
            "per_timeframe": {
                tf: {
                    "value":     sig.value,
                    "direction": sig.direction,
                    "rsi":       sig.rsi,
                    "sma_cross": sig.sma_cross,
                    "n_bars":    sig.n_bars,
                }
                for tf, sig in result.per_timeframe.items()
            },
        }
    except Exception:
        return {}


def _load_mtf_history(ticker: str, days: int = 60) -> pd.DataFrame:
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
        rows = db.query(
            "SELECT snapshot_date, confluence_value FROM mtf_snapshots "
            "WHERE ticker = ? AND snapshot_date >= CURRENT_DATE - INTERVAL ? DAY "
            "ORDER BY snapshot_date ASC",
            [ticker, days],
        )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["date", "value"])
        df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


def body_multi_timeframe(tokens: DesignTokens) -> None:  # pragma: no cover
    import streamlit as st

    render_section_header("⏱ Multi-Timeframe Analysis", "Confluence D · W · M con SignalBadge")

    cols_top = st.columns([3, 1, 1])
    with cols_top[1]:
        ticker = st.text_input("Ticker", value="SPY", key="q12_ticker", label_visibility="collapsed")
    with cols_top[2]:
        if st.button("🔄 Aggiorna", key="q12_refresh"):
            st.cache_data.clear()
            st.rerun()

    tab_live, tab_history = st.tabs(["📡 Live", "📈 Storico"])

    with tab_live:
        _render_live_tab(st, ticker, tokens)

    with tab_history:
        _render_history_tab(st, ticker, tokens)


def _render_live_tab(st, ticker: str, tokens: DesignTokens) -> None:  # pragma: no cover
    @st.cache_data(ttl=CACHE_TTL.MARKET_KPI)
    def _cached(t: str) -> dict:
        return _load_mtf_signal(t)

    with st.spinner(f"Analisi multi-timeframe per {ticker}..."):
        signal = _cached(ticker)

    if not signal:
        EmptyState(
            "Dati non disponibili",
            hint=f"Nessun OHLCV per {ticker} nel DB, o periodo storico insufficiente (min. 60 bar).",
            severity="warning",
        ).render()
        return

    render_section_header(f"Confluence — {ticker}")

    conv_color = {"high": "🟢", "moderate": "🟡", "low": "🔴"}.get(signal["conviction"], "⚪")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Confluence Score", f"{signal['confluence']:+.3f}")
    with col2:
        st.metric("Conviction", f"{conv_color} {signal['conviction'].capitalize()}")
    with col3:
        st.metric("Timeframe concordi", f"{signal['n_agreeing']} / 3")

    st.divider()
    render_section_header("Dettaglio per Timeframe")

    for tf, label in _TIMEFRAME_LABELS.items():
        tf_data = signal["per_timeframe"].get(tf)
        if tf_data is None:
            continue
        badge = SignalBadge(
            name=label,
            value=float(tf_data["value"]),
            confidence=1.0,
        )
        col_b, col_meta = st.columns([2, 3])
        with col_b:
            badge.render()
        with col_meta:
            st.caption(
                f"RSI: {tf_data['rsi']:.1f} · SMA cross: {tf_data['sma_cross']:+.3f} · "
                f"N bar: {tf_data['n_bars']} · Direzione: {tf_data['direction']}"
            )


def _render_history_tab(st, ticker: str, tokens: DesignTokens) -> None:  # pragma: no cover
    from presentation.ui.chart_theme import ChartFactory

    @st.cache_data(ttl=CACHE_TTL.MACRO_CONVICTION)
    def _cached(t: str, d: int) -> pd.DataFrame:
        return _load_mtf_history(t, d)

    days = st.slider("Periodo (giorni)", 7, 180, 60, key="q12_days")
    df = _cached(ticker, days)

    if df.empty:
        EmptyState(
            "Storico confluence non disponibile",
            hint="La tabella mtf_snapshots viene popolata dallo scheduler giornaliero.",
        ).render()
        return

    fig = ChartFactory.time_series(df, x="date", y="value",
                                   title=f"MTF Confluence — {ticker} ({days}d)")
    st.plotly_chart(fig, use_container_width=True)


if __name__ == "__main__":  # pragma: no cover
    render_page("Multi-Timeframe", "⏱", body_multi_timeframe)
