# ruff: noqa: N999
"""N1 — News Feed Live (v1.0).

Fase 7: feed RSS da 6 fonti reali (Reuters, CNBC, FT, Seeking Alpha, Nasdaq, Finviz).
Regola 33: zero articoli simulati — solo feed RSS reali.
Regola 34: timestamp aggiornamento visibile, cache 30 min.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "1.0.0"
__all__ = ["body_news_feed"]

_SENTIMENT_EMOJI = {
    "bullish":  "🟢",
    "bearish":  "🔴",
    "neutral":  "⚪",
}

_CATEGORY_EMOJI = {
    "earnings":     "💰",
    "macro":        "🌍",
    "geopolitics":  "⚔️",
    "central_bank": "🏦",
    "equity":       "📈",
    "commodities":  "🛢️",
    "crypto":       "₿",
    "unknown":      "📰",
}


def body_news_feed(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit
    import streamlit as st

    from engine.news.news_aggregator import NewsAggregator
    from engine.news.rss_fetcher import RSSFetcher
    from shared.db.duckdb_client import get_duckdb_client
    from shared.feature_flags import is_enabled

    render_section_header(
        "📰 News Feed Live",
        "6 fonti RSS reali · classificazione automatica · aggiornato ogni 30 min",
    )

    cols_top = st.columns([3, 1, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="n1_refresh"):
            st.cache_data.clear()
            st.rerun()
    with cols_top[2]:
        force_fetch = st.button("📥 Fetch ora", key="n1_force_fetch")

    if not is_enabled("news_engine_enabled"):
        st.warning("⚠️ News Engine non attivo. Abilita `news_engine_enabled` in feature_flags.yaml.")
        return

    if force_fetch:
        with st.spinner("Scaricamento notizie in corso..."):
            try:
                client = get_duckdb_client()
                fetcher = RSSFetcher(client)
                articles = fetcher.fetch_all()
                st.success(f"✅ Scaricati {len(articles)} articoli")
                st.cache_data.clear()
            except Exception as exc:
                st.error(f"Errore fetch: {exc}")

    @st.cache_data(ttl=1800)
    def _load_articles(limit: int = 50) -> list:
        try:
            rows = get_duckdb_client().query(
                "SELECT article_id, title, source, published_at, category, "
                "sentiment_score, impact_score, tickers_json, url "
                "FROM news_articles WHERE is_duplicate=FALSE "
                "ORDER BY published_at DESC LIMIT ?",
                [limit],
            )
            return rows or []
        except Exception:
            return []

    @st.cache_data(ttl=1800)
    def _load_signal() -> dict:
        try:
            client = get_duckdb_client()
            agg = NewsAggregator(client)
            signal = agg.run()
            return {
                "score": signal.score,
                "article_count": signal.article_count,
                "bullish": signal.bullish_count,
                "bearish": signal.bearish_count,
                "neutral": signal.neutral_count,
                "top_tickers": signal.top_tickers,
                "data_quality": signal.data_quality,
            }
        except Exception as exc:
            return {"error": str(exc)}

    # ── Segnale aggregato ─────────────────────────────────────────────────
    sig = _load_signal()
    if "error" not in sig:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            score = sig.get("score", 0.0)
            badge = "🟢 Bullish" if score > 0.2 else ("🔴 Bearish" if score < -0.2 else "⚪ Neutro")
            st.metric("News Sentiment", f"{score:+.2f}", help="Score aggregato [-1,+1]")
        with c2:
            st.metric("Articoli totali", sig.get("article_count", 0))
        with c3:
            st.metric("🟢 Bullish", sig.get("bullish", 0))
        with c4:
            st.metric("🔴 Bearish", sig.get("bearish", 0))
        top_t = sig.get("top_tickers", [])
        if top_t:
            st.caption(f"Ticker principali: {', '.join(top_t[:8])}")
    elif sig.get("error"):
        st.info(f"Segnale news: {sig['error'][:100]}")

    # ── Filtri ────────────────────────────────────────────────────────────
    st.divider()
    render_section_header("📋 Articoli")

    f_col1, f_col2, f_col3 = st.columns(3)
    with f_col1:
        cat_filter = st.selectbox(
            "Categoria",
            ["Tutte", "earnings", "macro", "central_bank", "geopolitics", "equity",
             "commodities", "crypto"],
            key="n1_cat_filter",
        )
    with f_col2:
        source_filter = st.text_input("Fonte (es. reuters)", key="n1_src_filter")
    with f_col3:
        n_articles = st.slider("Max articoli", 10, 100, 30, step=10, key="n1_n")

    articles = _load_articles(limit=100)

    # Applica filtri
    filtered = articles
    if cat_filter != "Tutte":
        filtered = [a for a in filtered if str(a[4]).lower() == cat_filter]
    if source_filter:
        filtered = [a for a in filtered if source_filter.lower() in str(a[2]).lower()]
    filtered = filtered[:n_articles]

    if not filtered:
        st.info(
            "Nessun articolo disponibile. Clicca '📥 Fetch ora' per scaricare notizie "
            "dalla 6 fonti RSS configurate (Reuters, CNBC, FT, Seeking Alpha, Nasdaq, Finviz)."
        )
        return

    st.caption(f"Mostrando {len(filtered)} articoli · Fonte: news_articles DB")

    for row in filtered:
        article_id, title, source, published_at, category, sent_score, impact, tickers_json, url = row

        cat_str = str(category) if category else "unknown"
        cat_key = cat_str.replace("NewsCategory.", "").lower()
        cat_emoji = _CATEGORY_EMOJI.get(cat_key, "📰")

        # Sentiment badge
        sent_val = float(sent_score) if sent_score is not None else 0.0
        if sent_val > 0.1:
            sent_label = "bullish"
        elif sent_val < -0.1:
            sent_label = "bearish"
        else:
            sent_label = "neutral"
        sent_emoji = _SENTIMENT_EMOJI[sent_label]

        ts_str = ""
        if published_at:
            try:
                import pandas as pd
                ts_str = pd.to_datetime(published_at).strftime("%d/%m %H:%M")
            except Exception:
                ts_str = str(published_at)[:16]

        header = f"{cat_emoji} **{title}** · {source} · {ts_str} · {sent_emoji}"
        with st.expander(header, expanded=False):
            c1, c2 = st.columns([2, 1])
            with c1:
                st.markdown(f"**Fonte:** {source}")
                st.markdown(f"**Categoria:** {cat_str}")
                if tickers_json:
                    import json as _json
                    try:
                        tickers = _json.loads(str(tickers_json))
                        if tickers:
                            st.markdown(f"**Ticker:** {', '.join(tickers[:5])}")
                    except Exception:
                        pass
            with c2:
                if sent_score is not None:
                    st.metric("Sentiment", f"{float(sent_score):+.2f}")
                if impact is not None:
                    st.metric("Impatto", f"{float(impact):.2f}")
            if url:
                st.link_button("🔗 Leggi articolo", url)


if __name__ == "__main__":  # pragma: no cover
    render_page("News Feed", "📰", body_news_feed)
