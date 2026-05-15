# ruff: noqa: N999
"""Q3 Correlations & Cross-Asset ★ aggiornato v8.2 (Blocco 4).

5 tab:
  1. Cross-Asset Matrix — heatmap correlazioni + diversification score
  2. Lead-Lag (Granger) — tabella coppie significative
  3. Regime Cross-Asset — correlazioni per regime (bull/bear/stress)
  4. EWMA Pairwise — top 10 correlazioni per magnitude
  5. Segnale Composito — contributo correlation al Composite v2.1
"""
from __future__ import annotations

__version__ = "8.2.0"
__all__ = ["body_q3_correlations"]


def body_q3_correlations(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()
    st.title("🔬 Correlation Engine v2 — Cross-Asset & Lead-Lag")
    st.caption("EWMA Enhanced · Granger Causality · Regime-Conditioned · DCC")

    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
    except Exception as exc:
        st.error(f"DB non disponibile: {exc}")
        return

    tab_matrix, tab_leadlag, tab_regime, tab_ewma, tab_signal = st.tabs([
        "🗺️ Cross-Asset Matrix",
        "⏱️ Lead-Lag Granger",
        "🎭 Regime Cross-Asset",
        "📉 EWMA Pairwise",
        "⚡ Segnale Composito",
    ])

    # ── Tab 1: Cross-Asset Heatmap ─────────────────────────────────────────
    with tab_matrix:
        st.subheader("Cross-Asset Correlation Matrix (13 asset)")
        try:
            rows = db.query(
                "SELECT regime_date, avg_equity_bond_corr, avg_equity_gold_corr, "
                "credit_equity_corr, diversification_score, correlation_signal, "
                "vix_correlation_regime "
                "FROM cross_asset_regime ORDER BY regime_date DESC LIMIT 1"
            )
            if not rows:
                st.info("Nessun dato disponibile. Eseguire CrossAssetMatrix.compute().")
            else:
                r = rows[0]
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    val = f"{r[4]:.3f}" if r[4] is not None else "N/A"
                    delta_color = "normal" if r[4] and r[4] > 0.5 else "inverse"
                    st.metric("Diversification Score", val, delta_color=delta_color)
                with c2:
                    val = f"{r[1]:.3f}" if r[1] is not None else "N/A"
                    st.metric("Equity/Bond Corr", val)
                with c3:
                    val = f"{r[2]:.3f}" if r[2] is not None else "N/A"
                    st.metric("Equity/Gold Corr", val)
                with c4:
                    val = f"{r[3]:.3f}" if r[3] is not None else "N/A"
                    st.metric("Credit/Equity Corr", val)

                regime = r[6] or "normal"
                regime_color = {"crisis_coupling": "🔴", "normal": "🟢", "divergence": "🟡"}.get(regime, "⚪")
                st.info(f"{regime_color} VIX Regime: **{regime.replace('_', ' ').title()}** — "
                        f"Correlation Signal: {r[5]:+.3f}" if r[5] else f"{regime_color} VIX Regime: {regime}")
                st.caption(f"Snapshot: {r[0]}")
        except Exception as exc:
            st.warning(f"Cross-asset data non disponibile: {exc}")

        st.divider()
        st.subheader("Storia Diversification Score")
        try:
            import pandas as pd
            import plotly.graph_objects as go
            rows = db.query(
                "SELECT regime_date, diversification_score, correlation_signal "
                "FROM cross_asset_regime ORDER BY regime_date ASC LIMIT 1000"
            )
            if rows:
                df = pd.DataFrame(rows, columns=["date", "div_score", "corr_signal"])
                df["date"] = pd.to_datetime(df["date"])
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df["date"], y=df["div_score"],
                    name="Diversification Score", mode="lines",
                    line=dict(color=tokens.colors.positive, width=2),
                    fill="tozeroy", fillcolor="rgba(0,200,100,0.1)",
                ))
                fig.add_hline(y=0.5, line_color="gray", line_dash="dot", opacity=0.4)
                fig.update_layout(
                    height=300, title="Diversification Score [0→1]",
                    yaxis=dict(range=[0, 1.05]),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=0, r=0, t=40, b=0),
                )
                st.plotly_chart(fig, use_container_width=True)
        except Exception as exc:
            st.caption(f"Storia non disponibile: {exc}")

    # ── Tab 2: Lead-Lag Granger ────────────────────────────────────────────
    with tab_leadlag:
        st.subheader("Lead-Lag Analysis — Granger Causality")
        st.caption("Solo coppie statisticamente significative (p < 0.05, |cross-corr| > 0.30)")
        try:
            import pandas as pd
            rows = db.query(
                "SELECT analysis_date, leader_asset, follower_asset, optimal_lag_days, "
                "granger_f_stat, granger_pvalue, cross_corr_peak, lead_signal "
                "FROM lead_lag_signals WHERE is_significant = TRUE "
                "ORDER BY analysis_date DESC, granger_pvalue ASC LIMIT 50"
            )
            if not rows:
                st.info("Nessun lead-lag significativo rilevato.")
            else:
                df = pd.DataFrame(rows, columns=[
                    "Data", "Leader", "Follower", "Lag (gg)",
                    "F-stat", "p-value", "Cross-Corr", "Segnale"
                ])
                df["p-value"] = df["p-value"].apply(lambda x: f"{x:.4f}" if x else "N/A")
                df["F-stat"]  = df["F-stat"].apply(lambda x: f"{x:.2f}" if x else "N/A")
                df["Cross-Corr"] = df["Cross-Corr"].apply(lambda x: f"{x:+.3f}" if x else "N/A")

                def _color_signal(s):
                    if s == "bullish_lead":
                        return f"🟢 {s}"
                    elif s == "bearish_lead":
                        return f"🔴 {s}"
                    return f"⚪ {s}"

                df["Segnale"] = df["Segnale"].apply(_color_signal)
                st.dataframe(df, use_container_width=True, hide_index=True)
        except Exception as exc:
            st.warning(f"Lead-lag non disponibile: {exc}")

    # ── Tab 3: Regime Cross-Asset ──────────────────────────────────────────
    with tab_regime:
        st.subheader("Correlazioni per Regime di Mercato")
        st.caption("Correlazioni condizionate per regime: bull / bear / stress / transition")
        try:
            import pandas as pd
            rows = db.query(
                "SELECT regime_date, avg_equity_bond_corr, avg_equity_gold_corr, "
                "credit_equity_corr, vix_correlation_regime "
                "FROM cross_asset_regime ORDER BY regime_date DESC LIMIT 90"
            )
            if not rows:
                st.info("Nessun dato regime disponibile.")
            else:
                import plotly.graph_objects as go
                df = pd.DataFrame(rows, columns=[
                    "date", "eq_bond", "eq_gold", "credit_eq", "vix_regime"
                ])
                df["date"] = pd.to_datetime(df["date"])
                fig = go.Figure()
                for col, label, color in [
                    ("eq_bond",   "Equity/Bond",   tokens.colors.info),
                    ("eq_gold",   "Equity/Gold",   tokens.colors.warning),
                    ("credit_eq", "Credit/Equity", tokens.colors.positive),
                ]:
                    if df[col].notna().any():
                        fig.add_trace(go.Scatter(
                            x=df["date"], y=df[col],
                            name=label, mode="lines",
                            line=dict(color=color, width=1.5),
                        ))
                fig.add_hline(y=0, line_color="gray", line_dash="dot", opacity=0.3)
                fig.update_layout(
                    height=350, title="Correlazioni Chiave nel Tempo",
                    yaxis=dict(range=[-1.1, 1.1]),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    legend=dict(orientation="h", y=1.1),
                    margin=dict(l=0, r=0, t=40, b=0),
                )
                st.plotly_chart(fig, use_container_width=True)
        except Exception as exc:
            st.warning(f"Dati regime non disponibili: {exc}")

    # ── Tab 4: EWMA Pairwise ───────────────────────────────────────────────
    with tab_ewma:
        st.subheader("Top Correlazioni EWMA (|ρ| maggiore)")
        st.caption("EWMA Enhanced con lambda ottimale via MLE · Ledoit-Wolf shrinkage")
        try:
            import pandas as pd
            rows = db.query(
                "SELECT analysis_date, leader_asset, follower_asset, "
                "cross_corr_peak, optimal_lag_days "
                "FROM lead_lag_signals "
                "ORDER BY ABS(cross_corr_peak) DESC LIMIT 20"
            )
            if not rows:
                st.info("Nessun dato EWMA disponibile.")
            else:
                df = pd.DataFrame(rows, columns=[
                    "Data", "Asset A", "Asset B", "Peak Cross-Corr", "Lag (gg)"
                ])
                df["Peak Cross-Corr"] = df["Peak Cross-Corr"].apply(
                    lambda x: f"{x:+.4f}" if x else "N/A"
                )
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.caption(
                    "Cross-corr misurata al lag ottimale selezionato da Granger test. "
                    "Valori vicino a ±1 = forte lead-lag relationship."
                )
        except Exception as exc:
            st.warning(f"EWMA data non disponibile: {exc}")

    # ── Tab 5: Segnale composito ───────────────────────────────────────────
    with tab_signal:
        st.subheader("Contributo Correlation al Composite Signal v2.1")
        try:
            import pandas as pd
            import plotly.graph_objects as go
            rows = db.query(
                "SELECT regime_date, correlation_signal, diversification_score "
                "FROM cross_asset_regime ORDER BY regime_date ASC LIMIT 500"
            )
            if not rows:
                st.info("Storico segnali non disponibile.")
            else:
                df = pd.DataFrame(rows, columns=["date", "signal", "div"])
                df["date"] = pd.to_datetime(df["date"])
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df["date"], y=df["signal"],
                    name="Correlation Signal", mode="lines",
                    line=dict(color=tokens.colors.primary, width=2),
                    fill="tozeroy", fillcolor="rgba(100,100,255,0.1)",
                ))
                fig.add_hline(y=0, line_color="gray", line_dash="dot", opacity=0.3)
                fig.update_layout(
                    height=350, title="Correlation Signal [-1, +1]",
                    yaxis=dict(range=[-1.1, 1.1]),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=0, r=0, t=40, b=0),
                )
                st.plotly_chart(fig, use_container_width=True)
                st.caption(
                    "**Peso nel Composite v2.1:** 5% · "
                    "Alta diversificazione → segnale positivo (mercato sano) · "
                    "Bassa diversificazione → segnale negativo (stress/crisis coupling)"
                )
        except Exception as exc:
            st.warning(f"Storico segnali non disponibile: {exc}")
