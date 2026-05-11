# ruff: noqa: N999
"""M4 — PMI & Leading Indicators ★ NUOVA (v8.0)."""
from __future__ import annotations

__version__ = "8.0.0"
__all__ = ["body_m4_pmi_leading_indicators"]


def body_m4_pmi_leading_indicators(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()
    st.title("🌍 Macro — PMI & Leading Indicators")
    st.caption("ISM Manufacturing, Industrial Production, Housing Starts, Sentiment.")

    try:
        import plotly.graph_objects as go
        from shared.db.macro_repo import get_macro_repository
        repo = get_macro_repository()

        series_cfg = [
            ("ISM Manufacturing (NAPM)", "NAPM", 50.0),
            ("Industrial Production (INDPRO)", "INDPRO", None),
            ("Housing Starts (HOUST)", "HOUST", 1400),
            ("UMich Sentiment (UMCSENT)", "UMCSENT", 70),
        ]

        col1, col2 = st.columns(2)
        panes = [col1, col2, col1, col2]

        for (label, sid, threshold), col in zip(series_cfg, panes):
            with col:
                try:
                    df = repo.read_macro(sid)
                    if df is None or df.empty:
                        st.caption(f"{label}: N/D")
                        continue
                    df_plot = df.tail(60)
                    latest  = float(df_plot["value"].dropna().iloc[-1])
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=df_plot["ts"], y=df_plot["value"],
                        mode="lines", line=dict(color="#3B82F6", width=2),
                        fill="tozeroy", fillcolor="#3B82F622",
                    ))
                    if threshold:
                        fig.add_hline(y=threshold, line_dash="dash",
                                      line_color="#6B7280",
                                      annotation_text=str(threshold))
                    fig.update_layout(
                        height=200, title=f"{label}: {latest:.1f}",
                        margin=dict(l=0, r=0, t=30, b=0), showlegend=False,
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)",
                    )
                    st.plotly_chart(fig, use_container_width=True)
                except Exception:
                    st.caption(f"{label}: dati non disponibili")
    except Exception as exc:
        st.warning(f"Dati PMI non disponibili: {exc}")
        st.info("Avvia lo scheduler per popolare i dati FRED.")
