# ruff: noqa: N999
"""Q5 — Sentiment Analysis (Blocco D).

Pattern: _load_*() pure + body_sentiment() Streamlit.
2 tab: Live · Storico
"""
from __future__ import annotations

import pandas as pd

from presentation.ui.cache_policy import CACHE_TTL
from presentation.ui.components import EmptyState
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "1.0.0"
__all__ = ["body_sentiment"]

_SOURCE_LABELS: dict[str, str] = {
    "cnn_fg":    "CNN Fear & Greed",
    "crypto_fg": "Crypto Fear & Greed",
    "put_call":  "Put/Call Ratio",
    "finnhub":   "Finnhub Sentiment",
    "aaii":      "AAII Bull-Bear",
    "cot":       "COT Net Position",
    "insider":   "Insider Activity",
    "short_int": "Short Interest",
}


def _load_sentiment_scores() -> dict:
    try:
        from engine.analytics.sentiment.live_sentiment_service import get_live_sentiment_service
        scores = get_live_sentiment_service().fetch_all()
        return scores.to_display_dict()
    except Exception:
        return {}


def _load_sentiment_history(days: int = 30) -> pd.DataFrame:
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
        rows = db.query(
            "SELECT snapshot_date, composite_score FROM sentiment_snapshots "
            "WHERE snapshot_date >= CURRENT_DATE - INTERVAL ? DAY "
            "ORDER BY snapshot_date ASC",
            [days],
        )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["date", "value"])
        df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


def body_sentiment(tokens: DesignTokens) -> None:  # pragma: no cover
    import streamlit as st

    render_section_header("🧠 Sentiment Analysis", "CNN F&G · AAII · COT · Insider · Short Interest")

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="q5_refresh"):
            st.cache_data.clear()
            st.rerun()

    tab_live, tab_history = st.tabs(["📡 Live", "📈 Storico"])

    with tab_live:
        _render_live_tab(st, tokens)

    with tab_history:
        _render_history_tab(st, tokens)


def _render_live_tab(st, tokens: DesignTokens) -> None:  # pragma: no cover
    @st.cache_data(ttl=CACHE_TTL.MARKET_KPI)
    def _cached() -> dict:
        return _load_sentiment_scores()

    with st.spinner("Fetch sentiment live..."):
        scores = _cached()

    if not scores:
        EmptyState(
            "Dati sentiment non disponibili",
            hint="Verifica la connessione a internet e la configurazione FINNHUB_API_KEY in .env.",
            severity="warning",
        ).render()
        return

    render_section_header("📡 Sentiment Live")

    pairs = list(_SOURCE_LABELS.items())
    for i in range(0, len(pairs), 4):
        cols = st.columns(4)
        for col, (key, label) in zip(cols, pairs[i:i + 4]):
            value = scores.get(key)
            with col:
                if value is None:
                    st.metric(label, "N/D")
                else:
                    color = tokens.colors.signal_color(float(value))
                    st.markdown(
                        f'<p style="font-size:12px;margin-bottom:2px">{label}</p>'
                        f'<p style="font-size:22px;font-weight:600;color:{color};margin:0">{value:+.2f}</p>',
                        unsafe_allow_html=True,
                    )

    st.caption("Score normalizzati [-1, +1]: +1 = estrema euforia · -1 = estremo panico")


def _render_history_tab(st, tokens: DesignTokens) -> None:  # pragma: no cover
    from presentation.ui.chart_theme import ChartFactory

    @st.cache_data(ttl=CACHE_TTL.MACRO_CONVICTION)
    def _cached(d: int) -> pd.DataFrame:
        return _load_sentiment_history(d)

    days = st.slider("Periodo (giorni)", 7, 180, 30, key="q5_days")
    df = _cached(days)

    if df.empty:
        EmptyState(
            "Storico sentiment non disponibile",
            hint="Nessun dato in sentiment_snapshots. Lo scheduler popola questa tabella ogni giorno.",
        ).render()
        return

    fig = ChartFactory.time_series(df, x="date", y="value", title="Composite Sentiment Score (30d)")
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"{len(df)} osservazioni · Fonte: sentiment_snapshots DB")


if __name__ == "__main__":  # pragma: no cover
    render_page("Sentiment Analysis", "🧠", body_sentiment)
