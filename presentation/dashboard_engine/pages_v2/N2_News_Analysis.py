# ruff: noqa: N999
"""N2 — News Analysis: heatmap sentiment + clustering (v1.0 — Fase 7).

Regola 33: nessun dato simulato — sentiment calcolato su articoli RSS reali.
Regola 34: lettura da news_signal e news_articles (DuckDB, TTL 1800s).
"""
from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["body_n2_news_analysis"]


def body_n2_news_analysis(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    st.title("📊 News — Analisi Sentiment & Clustering")
    st.caption("Segnale news [-1,+1] · Heatmap per sorgente e categoria · Cluster tematici")

    cols_top = st.columns([3, 1, 1])
    with cols_top[1]:
        if st.button("🔬 Ricalcola Segnale", key="n2_compute"):
            try:
                from shared.db.duckdb_client import get_duckdb_client
                from engine.news.news_aggregator import NewsAggregator
                db = get_duckdb_client()
                agg = NewsAggregator(client=db)
                signal = agg.run_pipeline()
                if signal:
                    st.success(f"Segnale ricalcolato: {signal.score:+.3f}")
                else:
                    st.warning("Nessun articolo recente disponibile per il segnale.")
            except Exception as exc:
                st.error(f"Errore pipeline: {exc}")
    with cols_top[2]:
        if st.button("🔄 Aggiorna", key="n2_refresh"):
            st.cache_data.clear()
            st.rerun()

    try:
        from shared.db.duckdb_client import get_duckdb_client
        import pandas as pd
        db = get_duckdb_client()
    except Exception as exc:
        st.error(f"DB non disponibile: {exc}")
        return

    tab_signal, tab_heatmap, tab_clusters = st.tabs([
        "⚡ Segnale News",
        "🗺️ Heatmap Sentiment",
        "🔵 Cluster Tematici",
    ])

    # ── Tab 1: Segnale news corrente ─────────────────────────────────────────
    with tab_signal:
        st.subheader("Segnale News — Composite Signal v3")
        try:
            rows = db.query(
                "SELECT signal_date, score, article_count, bullish_count, bearish_count, "
                "dominant_category, data_quality "
                "FROM news_signal ORDER BY signal_date DESC LIMIT 1"
            )
            if not rows:
                st.info("Nessun segnale news calcolato. Clicca **🔬 Ricalcola Segnale**.")
            else:
                r = rows[0]
                score = float(r[1])
                label = "🟢 BULLISH" if score > 0.2 else "🔴 BEARISH" if score < -0.2 else "🟡 NEUTRO"
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Score News", f"{score:+.3f}", label)
                col2.metric("Articoli", str(r[2] or 0))
                col3.metric("Bullish", str(r[3] or 0))
                col4.metric("Bearish", str(r[4] or 0))
                if r[5]:
                    st.caption(f"Categoria dominante: **{r[5]}** · Qualità: {r[6]} · {r[0]}")

                # Trend storico
                hist_rows = db.query(
                    "SELECT signal_date, score FROM news_signal "
                    "ORDER BY signal_date DESC LIMIT 14"
                )
                if len(hist_rows) >= 3:
                    import plotly.graph_objects as go
                    dates = [r[0] for r in reversed(hist_rows)]
                    scores = [float(r[1]) for r in reversed(hist_rows)]
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=dates, y=scores, mode="lines+markers",
                        line={"color": "royalblue", "width": 2},
                        name="News Score",
                    ))
                    fig.add_hline(y=0, line_dash="dash", line_color="gray")
                    fig.update_layout(
                        title="Segnale News — Ultimi 14 giorni",
                        yaxis={"range": [-1, 1], "title": "Score"},
                        height=300, margin={"t": 40, "b": 20},
                    )
                    st.plotly_chart(fig, use_container_width=True)
        except Exception as exc:
            st.warning(f"Segnale non disponibile: {exc}")

    # ── Tab 2: Heatmap sentiment per sorgente ─────────────────────────────────
    with tab_heatmap:
        st.subheader("Heatmap Sentiment per Sorgente e Categoria")
        try:
            rows = db.query(
                "SELECT source, category, COUNT(*) as cnt "
                "FROM news_articles "
                "WHERE published_at >= NOW() - INTERVAL 3 DAY "
                "GROUP BY source, category ORDER BY source, category"
            )
            if not rows:
                st.info("Nessun articolo negli ultimi 3 giorni.")
            else:
                import plotly.express as px
                df = pd.DataFrame(rows, columns=["source", "category", "count"])
                pivot = df.pivot_table(
                    index="source", columns="category", values="count", fill_value=0
                )
                fig = px.imshow(
                    pivot,
                    labels={"x": "Categoria", "y": "Sorgente", "color": "Articoli"},
                    title="Distribuzione Articoli per Sorgente × Categoria (ultimi 3 giorni)",
                    color_continuous_scale="Blues",
                    aspect="auto",
                )
                fig.update_layout(height=350, margin={"t": 50, "b": 20})
                st.plotly_chart(fig, use_container_width=True)
        except Exception as exc:
            st.warning(f"Heatmap non disponibile: {exc}")

    # ── Tab 3: Cluster tematici ────────────────────────────────────────────────
    with tab_clusters:
        st.subheader("Cluster Tematici — TF-IDF + DBSCAN")
        try:
            rows = db.query(
                "SELECT cluster_id, cluster_label, article_count, "
                "avg_sentiment_score, created_at "
                "FROM news_clusters "
                "ORDER BY created_at DESC, article_count DESC LIMIT 20"
            )
            if not rows:
                st.info(
                    "Nessun cluster disponibile. "
                    "Usare NewsEventClusterer per generare cluster."
                )
            else:
                import plotly.express as px
                df = pd.DataFrame(rows, columns=[
                    "cluster_id", "label", "articles", "avg_sentiment", "created_at"
                ])
                fig = px.bar(
                    df,
                    x="label",
                    y="articles",
                    color="avg_sentiment",
                    color_continuous_scale="RdYlGn",
                    range_color=[-1, 1],
                    title="Cluster tematici — volumi e sentiment",
                    labels={"label": "Cluster", "articles": "Articoli", "avg_sentiment": "Sentiment"},
                )
                fig.update_layout(height=350, margin={"t": 50, "b": 20})
                st.plotly_chart(fig, use_container_width=True)

                for _, row in df.iterrows():
                    sent = float(row["avg_sentiment"]) if row["avg_sentiment"] else 0.0
                    icon = "🟢" if sent > 0.1 else "🔴" if sent < -0.1 else "🟡"
                    st.markdown(
                        f"{icon} **{row['label']}** — {row['articles']} articoli "
                        f"· sentiment: {sent:+.2f}"
                    )
        except Exception as exc:
            st.warning(f"Cluster non disponibili: {exc}")
