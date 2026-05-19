# ruff: noqa: N999
"""N2 — News Analysis (v1.0).

Fase 7: analisi aggregata del news engine — heatmap per categoria e fonte,
sentiment trend, clustering TF-IDF, LLM latente.
Regola 33: zero notizie simulate.
Regola 34: tutti i dati da DB, TTL 30 min.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "1.0.0"
__all__ = ["body_news_analysis"]


def body_news_analysis(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit
    import streamlit as st

    from shared.db.duckdb_client import get_duckdb_client
    from shared.feature_flags import is_enabled

    render_section_header(
        "📊 News Analysis",
        "Heatmap sentiment · cluster eventi · analisi per fonte — dati reali RSS",
    )

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="n2_refresh"):
            st.cache_data.clear()
            st.rerun()

    if not is_enabled("news_engine_enabled"):
        st.warning("⚠️ News Engine non attivo. Abilita `news_engine_enabled` in feature_flags.yaml.")
        return

    @st.cache_data(ttl=1800)
    def _load_sentiment_by_category() -> list:
        try:
            return get_duckdb_client().query(
                "SELECT category, "
                "AVG(CASE WHEN sentiment_score IS NOT NULL THEN sentiment_score ELSE 0 END) as avg_sent, "
                "COUNT(*) as cnt "
                "FROM news_articles WHERE is_duplicate=FALSE "
                "AND published_at >= NOW() - INTERVAL '7 days' "
                "GROUP BY category ORDER BY avg_sent DESC"
            ) or []
        except Exception:
            return []

    @st.cache_data(ttl=1800)
    def _load_sentiment_by_source() -> list:
        try:
            return get_duckdb_client().query(
                "SELECT source, "
                "AVG(CASE WHEN sentiment_score IS NOT NULL THEN sentiment_score ELSE 0 END) as avg_sent, "
                "COUNT(*) as cnt "
                "FROM news_articles WHERE is_duplicate=FALSE "
                "AND published_at >= NOW() - INTERVAL '7 days' "
                "GROUP BY source ORDER BY cnt DESC LIMIT 20"
            ) or []
        except Exception:
            return []

    @st.cache_data(ttl=1800)
    def _load_sentiment_trend(days: int = 7) -> list:
        try:
            return get_duckdb_client().query(
                "SELECT CAST(published_at AS DATE) as day, "
                "AVG(CASE WHEN sentiment_score IS NOT NULL THEN sentiment_score ELSE 0 END) as avg_sent, "
                "COUNT(*) as cnt "
                "FROM news_articles WHERE is_duplicate=FALSE "
                "AND published_at >= NOW() - INTERVAL '? days' "
                "GROUP BY day ORDER BY day",
                [days],
            ) or []
        except Exception:
            return []

    @st.cache_data(ttl=1800)
    def _load_clusters() -> list:
        try:
            return get_duckdb_client().query(
                "SELECT cluster_id, COUNT(*) as cnt, "
                "AVG(CASE WHEN sentiment_score IS NOT NULL THEN sentiment_score ELSE 0 END) as avg_sent, "
                "MIN(published_at) as first_seen "
                "FROM news_articles "
                "WHERE cluster_id IS NOT NULL AND is_duplicate=FALSE "
                "AND published_at >= NOW() - INTERVAL '3 days' "
                "GROUP BY cluster_id HAVING COUNT(*) >= 2 "
                "ORDER BY cnt DESC LIMIT 20"
            ) or []
        except Exception:
            return []

    # ── SEZIONE A — Heatmap Sentiment per Categoria ───────────────────────
    st.divider()
    render_section_header("🌡️ Sentiment per Categoria (7 giorni)")

    cat_rows = _load_sentiment_by_category()
    if cat_rows:
        import pandas as pd
        import plotly.graph_objects as go

        df_cat = pd.DataFrame(cat_rows, columns=["Categoria", "Sentiment Medio", "Articoli"])
        df_cat["Categoria"] = df_cat["Categoria"].astype(str).str.replace("NewsCategory.", "")
        df_cat["Sentiment Medio"] = df_cat["Sentiment Medio"].astype(float).round(3)

        colors = [
            "#2ecc71" if v > 0.1 else ("#e74c3c" if v < -0.1 else "#95a5a6")
            for v in df_cat["Sentiment Medio"]
        ]
        fig = go.Figure(go.Bar(
            x=df_cat["Categoria"],
            y=df_cat["Sentiment Medio"],
            marker_color=colors,
            text=df_cat["Articoli"].astype(str) + " art.",
            textposition="outside",
        ))
        fig.update_layout(
            height=300, margin=dict(l=0, r=0, t=20, b=0),
            plot_bgcolor=tokens.bg_secondary, paper_bgcolor=tokens.bg_secondary,
            font=dict(color=tokens.text_primary),
            yaxis_title="Sentiment [-1,+1]",
            yaxis=dict(range=[-1.1, 1.1]),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Fonte: news_articles DB · ultimi 7 giorni")
    else:
        st.info("Nessun dato disponibile. Fetch notizie da N1_News_Feed per popolare il DB.")

    # ── SEZIONE B — Sentiment per Fonte ──────────────────────────────────
    st.divider()
    render_section_header("📡 Sentiment per Fonte")

    src_rows = _load_sentiment_by_source()
    if src_rows:
        import pandas as pd
        df_src = pd.DataFrame(src_rows, columns=["Fonte", "Sentiment Medio", "Articoli"])
        df_src["Sentiment Medio"] = df_src["Sentiment Medio"].astype(float).round(3)
        df_src = df_src.sort_values("Articoli", ascending=False)
        st.dataframe(
            df_src.style.background_gradient(subset=["Sentiment Medio"], cmap="RdYlGn", vmin=-1, vmax=1),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Nessun dato per fonte.")

    # ── SEZIONE C — Trend Sentiment Giornaliero ───────────────────────────
    st.divider()
    render_section_header("📈 Trend Sentiment Giornaliero")

    trend_days = st.slider("Ultimi N giorni", 3, 30, 7, key="n2_trend_days")
    trend_rows = _load_sentiment_trend(trend_days)

    if trend_rows:
        import pandas as pd
        import plotly.graph_objects as go

        df_trend = pd.DataFrame(trend_rows, columns=["Giorno", "Sentiment Medio", "Articoli"])
        df_trend["Giorno"] = pd.to_datetime(df_trend["Giorno"])
        df_trend["Sentiment Medio"] = df_trend["Sentiment Medio"].astype(float)

        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=df_trend["Giorno"], y=df_trend["Sentiment Medio"],
            fill="tozeroy", name="Sentiment",
            line=dict(color=tokens.accent_primary, width=2),
            fillcolor=f"rgba(52, 152, 219, 0.15)",
        ))
        fig2.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
        fig2.update_layout(
            height=280, margin=dict(l=0, r=0, t=10, b=0),
            plot_bgcolor=tokens.bg_secondary, paper_bgcolor=tokens.bg_secondary,
            font=dict(color=tokens.text_primary),
            yaxis_title="Sentiment",
            yaxis=dict(range=[-1.1, 1.1]),
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("Dati trend non disponibili.")

    # ── SEZIONE D — Cluster Eventi ────────────────────────────────────────
    st.divider()
    render_section_header("🔗 Cluster di Notizie (TF-IDF + DBSCAN)")

    cluster_rows = _load_clusters()
    if cluster_rows:
        import pandas as pd
        df_cl = pd.DataFrame(cluster_rows, columns=["Cluster ID", "Articoli", "Sentiment Medio", "Prima apparizione"])
        df_cl["Sentiment Medio"] = df_cl["Sentiment Medio"].astype(float).round(3)
        df_cl["Prima apparizione"] = pd.to_datetime(df_cl["Prima apparizione"]).dt.strftime("%d/%m %H:%M")
        st.dataframe(df_cl, use_container_width=True, hide_index=True)
        st.caption(f"{len(cluster_rows)} cluster attivi (ultimi 3 giorni) · Fonte: news_articles DB")
    else:
        st.info("Nessun cluster attivo. I cluster vengono calcolati durante il fetch RSS.")

    # ── SEZIONE E — LLM News Analysis ────────────────────────────────────
    st.divider()
    render_section_header("🤖 Analisi Semantica LLM")

    if is_enabled("news_llm_analysis") and is_enabled("llm_engine_enabled"):
        try:
            from engine.llm.news_semantic_analyzer import NewsSemanticAnalyzer
            analyzer = NewsSemanticAnalyzer()
            summary = analyzer.summarize_today()
            st.success("🤖 **Analisi LLM attiva**")
            st.markdown(summary)
        except Exception as exc:
            st.warning(f"LLM Analysis fallback: {exc}")
    else:
        st.info(
            "🔒 **Analisi LLM non attiva.** "
            "Attiva `llm_engine_enabled` e `news_llm_analysis` da S2_Settings "
            "dopo aver configurato Ollama (mistral:7b-q4)."
        )


if __name__ == "__main__":  # pragma: no cover
    render_page("News Analysis", "📊", body_news_analysis)
