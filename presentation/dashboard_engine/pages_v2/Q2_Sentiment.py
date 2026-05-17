# ruff: noqa: N999
"""Q2 Sentiment (v8.1) — live da CNN F&G, Crypto F&G, CBOE Put/Call, Finnhub."""
from __future__ import annotations

__version__ = "8.1.0"
__all__ = ["body_q2_sentiment"]


def body_q2_sentiment(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    st.title("🔬 Analisi — Sentiment & Breadth")
    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="q2_refresh"):
            st.cache_data.clear()
            st.rerun()

    @st.cache_data(ttl=900)
    def _fetch_sentiment():
        from engine.analytics.sentiment.live_sentiment_service import (
            _DEMO_SCORES,
            get_live_sentiment_service,
        )
        svc = get_live_sentiment_service()
        result = svc.fetch_all()
        return result.to_display_dict(fallbacks=_DEMO_SCORES), result.live_sources, result.demo_sources, result.errors

    scores, live_srcs, demo_srcs, errors = _fetch_sentiment()

    # Status
    if live_srcs:
        st.success(f"✅ Live: {', '.join(live_srcs)}" + (f" · Demo: {', '.join(demo_srcs)}" if demo_srcs else ""))
    else:
        st.warning("⚠️ Tutte le fonti demo — configura FINNHUB_API_KEY in .env o verifica la connessione.")

    # Radar
    import pandas as pd
    import plotly.graph_objects as go

    labels = list(scores.keys())
    values = [scores[l] for l in labels]
    # Normalize [-1,+1] → [0,100] per il radar
    values_norm = [(v + 1) * 50 for v in values]

    fig = go.Figure(go.Scatterpolar(
        r=values_norm + [values_norm[0]],
        theta=labels + [labels[0]],
        fill="toself",
        line_color="royalblue",
    ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        showlegend=False,
        height=400,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Tabella dettaglio
    df = pd.DataFrame([
        {
            "Fonte": label,
            "Score": f"{v:+.2f}",
            "Sentiment": "🟢 BULLISH" if v > 0.3 else ("🔴 BEARISH" if v < -0.3 else "⚪ NEUTRO"),
            "Fonte": "🟢 LIVE" if label in live_srcs else "⚠️ DEMO",
        }
        for label, v in scores.items()
    ])
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Errori dettaglio
    if errors:
        with st.expander(f"🔍 Dettaglio errori ({len(errors)})", expanded=False):
            for src, err in errors.items():
                st.write(f"- **{src}**: {err}")

    # Composite score
    live_vals = [scores[l] for l in live_srcs if l in scores]
    if live_vals:
        composite = sum(live_vals) / len(live_vals)
        st.divider()
        st.metric(
            "Composite Sentiment (fonti live)",
            f"{composite:+.3f}",
            delta="Extreme Greed" if composite > 0.6 else ("Extreme Fear" if composite < -0.6 else "Neutro"),
        )
