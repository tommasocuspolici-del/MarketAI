# ruff: noqa: N999
"""Q1 — VIX-Based Analysis ★ NUOVA (v8.0)."""
from __future__ import annotations

__version__ = "8.0.0"
__all__ = ["body_q1_vix_based_analysis"]


def body_q1_vix_based_analysis(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()
    st.title("🔬 Analisi — VIX-Based Strategy")
    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="q1_refresh"):
            st.cache_data.clear()
            st.rerun()
    st.caption("Segnale VIX Z-Score regime-aware + StrategyComposer output.")

    # ── Strategy output corrente ───────────────────────────────────────────
    st.subheader("⚡ Segnale Corrente")
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
        rows = db.query(
            "SELECT computed_at, vix_signal, action, composite_score, "
            "confidence, regime_used, threshold_adjusted "
            "FROM vix_strategy_outputs ORDER BY computed_at DESC LIMIT 1"
        )
        if rows:
            r = rows[0]
            action_color = {"BUY": "#10B981", "HOLD": "#6B7280", "REDUCE": "#EF4444"}
            color = action_color.get(str(r[2]), "#6B7280")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Action",   str(r[2]))
            col2.metric("VIX Signal",  f"{float(r[1]):.3f}" if r[1] else "N/D")
            col3.metric("Composite",   f"{float(r[3]):+.3f}" if r[3] else "N/D")
            col4.metric("Confidence",  str(r[4]))
            st.markdown(
                f'<div style="padding:8px;border-left:4px solid {color};'
                f'border-radius:4px;background:{color}11">'
                f'Regime HMM: <b>{r[5] or "N/D"}</b> | '
                f'Threshold Z-Score: <b>{float(r[6]):.2f}</b> | '
                f'Calcolato: {r[0]}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.info("Nessun segnale VIX ancora calcolato.")
    except Exception as exc:
        st.warning(f"VIX strategy non disponibile: {exc}")

    st.divider()

    # ── Storico VIX signals ────────────────────────────────────────────────
    st.subheader("📈 Storico VIX Signals")
    try:
        import plotly.graph_objects as go
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()

        rows = db.query(
            "SELECT computed_at, vix_level, vix_zscore, regime "
            "FROM vix_signals ORDER BY computed_at DESC LIMIT 90"
        )
        if rows:
            import pandas as pd
            df = pd.DataFrame(rows, columns=["ts", "vix", "zscore", "regime"])
            df = df.sort_values("ts")

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df["ts"], y=df["vix"],
                mode="lines", name="VIX Level",
                line=dict(color="#EF4444", width=2),
            ))
            fig.add_hline(y=20, line_dash="dot", line_color="#F59E0B",
                          annotation_text="VIX 20")
            fig.add_hline(y=30, line_dash="dot", line_color="#EF4444",
                          annotation_text="VIX 30")
            fig.update_layout(
                height=250, margin=dict(l=0, r=0, t=20, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig, use_container_width=True)

            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(
                x=df["ts"], y=df["zscore"],
                mode="lines", name="Z-Score",
                line=dict(color="#3B82F6", width=1.5),
            ))
            fig2.add_hline(y=1.5,  line_dash="dash", line_color="#10B981",
                           annotation_text="BUY threshold")
            fig2.add_hline(y=-1.0, line_dash="dash", line_color="#EF4444",
                           annotation_text="REDUCE threshold")
            fig2.add_hline(y=0, line_color="#6B7280", line_width=0.5)
            fig2.update_layout(
                height=180, margin=dict(l=0, r=0, t=20, b=0),
                yaxis_title="Z-Score",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Nessun dato VIX storico disponibile.")
    except Exception as exc:
        st.warning(f"Storico VIX non disponibile: {exc}")
