# ruff: noqa: N999
"""N1 — News Feed live (v1.0 — Fase 7 CP-03).

Feed notizie in tempo reale da 6 fonti RSS.
Regola 33: nessun articolo simulato — solo feed RSS reali.
Regola 34: articoli letti da DuckDB (TTL 1800s), non ri-scaricati ad ogni query.
"""
from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["body_n1_news_feed"]


def body_n1_news_feed(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    st.title("📰 News — Feed Live")
    st.caption("6 fonti RSS · aggiornamento ogni 30 min · cache DuckDB")

    cols_top = st.columns([3, 1, 1])
    with cols_top[1]:
        if st.button("📥 Aggiorna Feed", key="n1_fetch"):
            try:
                from shared.db.duckdb_client import get_duckdb_client
                from engine.news.rss_fetcher import RSSFetcher
                db = get_duckdb_client()
                fetcher = RSSFetcher(client=db)
                articles = fetcher.fetch_all()
                st.success(f"Scaricati {len(articles)} articoli.")
            except Exception as exc:
                st.error(f"Fetch fallito: {exc}")
    with cols_top[2]:
        if st.button("🔄 Aggiorna", key="n1_refresh"):
            st.cache_data.clear()
            st.rerun()

    # ── Filtri ────────────────────────────────────────────────────────────────
    col_src, col_cat, col_days = st.columns(3)
    with col_src:
        source_filter = st.selectbox(
            "Sorgente",
            ["Tutte", "reuters", "cnbc", "financial_times", "seeking_alpha", "nasdaq_news", "finviz"],
            key="n1_source",
        )
    with col_cat:
        category_filter = st.selectbox(
            "Categoria",
            ["Tutte", "macro", "central_bank", "earnings", "geopolitics", "commodities", "crypto", "equity"],
            key="n1_category",
        )
    with col_days:
        days_back = st.slider("Ultimi N giorni", 1, 7, 2, key="n1_days")

    # ── Query DB ──────────────────────────────────────────────────────────────
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()

        conditions = ["published_at >= NOW() - INTERVAL ? DAY"]
        params: list[object] = [days_back]

        if source_filter != "Tutte":
            conditions.append("source = ?")
            params.append(source_filter)
        if category_filter != "Tutte":
            conditions.append("category = ?")
            params.append(category_filter)

        where = " AND ".join(conditions)
        rows = db.query(
            f"SELECT title, source, category, published_at, url, summary "
            f"FROM news_articles WHERE {where} "
            f"ORDER BY published_at DESC LIMIT 100",
            params,
        )

        if not rows:
            st.info(
                "Nessun articolo trovato nel periodo selezionato. "
                "Clicca **📥 Aggiorna Feed** per scaricare gli articoli."
            )
            return

        st.markdown(f"**{len(rows)} articoli** trovati")

        # Timestamp ultimo aggiornamento (Regola 34)
        ts_rows = db.query(
            "SELECT MAX(fetched_at) FROM news_articles"
        )
        if ts_rows and ts_rows[0][0]:
            st.caption(f"Ultimo aggiornamento cache: {ts_rows[0][0]}")

        st.divider()

        # ── Articoli ──────────────────────────────────────────────────────────
        for row in rows:
            title, source, category, pub_at, url, summary = row
            cat_icon = {
                "macro": "🌐", "central_bank": "🏦", "earnings": "💰",
                "geopolitics": "🌍", "commodities": "⛽", "crypto": "₿",
                "equity": "📈",
            }.get(category or "", "📰")

            with st.container():
                col_info, col_link = st.columns([5, 1])
                with col_info:
                    pub_str = pub_at.strftime("%d/%m %H:%M") if hasattr(pub_at, "strftime") else str(pub_at)
                    st.markdown(
                        f"**{title}**  \n"
                        f"{cat_icon} `{source}` · `{category or 'N/A'}` · {pub_str}"
                    )
                    if summary:
                        st.caption(summary[:200] + ("…" if len(summary) > 200 else ""))
                with col_link:
                    if url:
                        st.link_button("→ Leggi", url, use_container_width=True)
            st.divider()

    except Exception as exc:
        st.error(f"Errore lettura DB: {exc}")
        st.info("Verificare che la migration 20260901_027_news_engine.sql sia applicata.")
