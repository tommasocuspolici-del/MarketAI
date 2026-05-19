# ruff: noqa: N999
"""S1 — Analysis Pipeline & Signal Quality (v2.0 — Fase 4).

Sezioni:
  1. Composite Signal corrente (v3 con pattern)
  2. Signal Quality — IC tracking per segnale (AlphaDecayMonitor)
  3. Ensemble weights ICWeightedEnsembleComposer
  4. Pipeline jobs status (scheduler heartbeat)
  5. Walk-forward validation OOS per strategia
"""
from __future__ import annotations

__version__ = "2.0.0"
__all__ = ["body_s1_analysis_pipeline"]


def body_s1_analysis_pipeline(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    st.title("📡 Analysis Pipeline & Signal Quality")
    st.caption("Stato pipeline dati · IC tracking · ensemble weights · walk-forward validation")

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="s1_refresh"):
            st.cache_data.clear()
            st.rerun()

    tab_signal, tab_quality, tab_ensemble, tab_pipeline, tab_wf = st.tabs([
        "🔬 Composite Signal",
        "📊 Signal Quality (IC)",
        "⚖️ Ensemble Weights",
        "⚙️ Pipeline Jobs",
        "🧪 Walk-Forward",
    ])

    # ── Tab 1: Composite Signal ───────────────────────────────────────────────
    with tab_signal:
        st.subheader("🔬 Composite Signal v3")
        try:
            from shared.db.duckdb_client import get_duckdb_client
            db = get_duckdb_client()
            rows = db.query(
                "SELECT computed_at, composite_score, recommended_action, confidence, "
                "breakdown_json FROM engine_composite_signal "
                "ORDER BY computed_at DESC LIMIT 1"
            )
            if not rows:
                st.info("Nessun Composite Signal calcolato. Esegui il scheduler.")
            else:
                import json
                r = rows[0]
                score  = float(r[1])
                action = str(r[2])
                conf   = str(r[3])
                label  = "🟢 BUY" if action == "BUY" else ("🔴 REDUCE" if action == "REDUCE" else "⚪ HOLD")
                col1, col2, col3 = st.columns(3)
                col1.metric("Composite Score", f"{score:+.3f}", label)
                col2.metric("Action", action)
                col3.metric("Confidence", conf)
                st.caption(f"Calcolato: {r[0]}")
                if r[4]:
                    try:
                        bd = json.loads(r[4])
                        st.markdown("**Breakdown componenti:**")
                        for comp, val in sorted(bd.items(), key=lambda x: abs(x[1]), reverse=True):
                            bar = max(0.0, min(1.0, (float(val) + 1.0) / 2.0))
                            icon = "🟢" if float(val) > 0.1 else ("🔴" if float(val) < -0.1 else "🟡")
                            st.progress(bar, text=f"{icon} **{comp}**: {float(val):+.3f}")
                    except Exception:
                        pass
        except Exception as exc:
            st.warning(f"Composite Signal non disponibile: {exc}")

        st.divider()
        try:
            import pandas as pd
            import plotly.graph_objects as go
            from shared.db.duckdb_client import get_duckdb_client
            rows_h = get_duckdb_client().query(
                "SELECT computed_at, composite_score FROM engine_composite_signal "
                "ORDER BY computed_at DESC LIMIT 30"
            )
            if rows_h and len(rows_h) >= 3:
                df_h = pd.DataFrame(rows_h, columns=["ts", "score"]).sort_values("ts")
                fig = go.Figure(go.Scatter(
                    x=df_h["ts"], y=df_h["score"].astype(float),
                    mode="lines+markers", line=dict(color=tokens.accent_primary, width=2),
                ))
                fig.add_hline(y=0, line_dash="dash", line_color="gray")
                fig.update_layout(
                    height=200, margin=dict(l=0, r=0, t=10, b=0),
                    plot_bgcolor=tokens.bg_secondary, paper_bgcolor=tokens.bg_secondary,
                    font=dict(color=tokens.text_primary),
                    yaxis=dict(range=[-1.05, 1.05], title="Score"),
                )
                st.plotly_chart(fig, use_container_width=True)
        except Exception:
            pass

    # ── Tab 2: Signal Quality (IC) ────────────────────────────────────────────
    with tab_quality:
        st.subheader("📊 Information Coefficient (IC) per Segnale")
        st.caption(
            "IC = correlazione Spearman segnale vs rendimento futuro. "
            "IC < 0.02 → segnale non informativo · IC > 0.05 → affidabile."
        )
        try:
            import pandas as pd
            import plotly.graph_objects as go
            from shared.alpha_decay_monitor import AlphaDecayMonitor, IC_MIN_THRESHOLD
            monitor = AlphaDecayMonitor()
            signal_names = [
                "vix_signal", "macro_conviction", "labour_regime_signal",
                "sentiment_composite", "valuation_signal",
                "economic_surprise_index", "technical_composite",
                "pattern_signal", "news_signal",
            ]
            rows_q = []
            ic_vals = []
            for sig in signal_names:
                ic, flag = monitor.check_decay(sig)
                rows_q.append({
                    "Segnale": sig,
                    "IC": f"{ic:.4f}" if ic is not None else "N/D",
                    "Status": "✅ OK" if flag == "ok" else ("⚠️ Low IC" if flag == "low_ic" else "📊 Dati insufficienti"),
                })
                ic_vals.append(float(ic) if ic is not None else 0.0)

            st.dataframe(pd.DataFrame(rows_q), use_container_width=True, hide_index=True)
            st.caption(f"Soglia min IC: {IC_MIN_THRESHOLD:.3f}")

            colors = ["#10B981" if v >= 0.05 else ("#F59E0B" if v >= 0.02 else "#EF4444") for v in ic_vals]
            fig_ic = go.Figure(go.Bar(
                x=signal_names, y=ic_vals, marker_color=colors,
                text=[f"{v:.3f}" for v in ic_vals], textposition="outside",
            ))
            fig_ic.add_hline(y=IC_MIN_THRESHOLD, line_dash="dash", line_color="red")
            fig_ic.update_layout(
                height=260, margin=dict(l=0, r=0, t=20, b=80),
                plot_bgcolor=tokens.bg_secondary, paper_bgcolor=tokens.bg_secondary,
                font=dict(color=tokens.text_primary),
                xaxis=dict(tickangle=-30), yaxis_title="IC",
            )
            st.plotly_chart(fig_ic, use_container_width=True)
        except Exception as exc:
            st.warning(f"IC tracking non disponibile: {exc}")

    # ── Tab 3: Ensemble Weights ───────────────────────────────────────────────
    with tab_ensemble:
        st.subheader("⚖️ IC-Weighted Ensemble — Pesi per Strategia")
        st.caption("Peso proporzionale all'IC. IC < 0.02 → peso zero.")
        try:
            import pandas as pd
            import plotly.graph_objects as go
            from engine.strategy_lab.ensemble_composer import ICWeightedEnsembleComposer
            from shared.alpha_decay_monitor import AlphaDecayMonitor
            monitor = AlphaDecayMonitor()
            composer = ICWeightedEnsembleComposer(decay_monitor=monitor)
            signals = {s: 0.0 for s in [
                "vix", "macro", "yield_curve", "credit", "claims",
                "labour_market", "surprise", "valuation", "pattern",
            ]}
            result = composer.compose(signals)
            rows_e = [
                {"Strategia": s, "Peso": round(w, 4), "% totale": f"{w*100:.1f}%"}
                for s, w in sorted(result.weights.items(), key=lambda x: x[1], reverse=True)
            ]
            st.dataframe(pd.DataFrame(rows_e), use_container_width=True, hide_index=True)
            st.metric("Strategie attive", str(sum(1 for w in result.weights.values() if w > 0)))
            active = {k: v for k, v in result.weights.items() if v > 0.001}
            if active:
                fig_e = go.Figure(go.Pie(
                    labels=list(active.keys()), values=list(active.values()), hole=0.3
                ))
                fig_e.update_layout(
                    height=280, margin=dict(l=0, r=0, t=10, b=0),
                    paper_bgcolor=tokens.bg_secondary, font=dict(color=tokens.text_primary),
                )
                st.plotly_chart(fig_e, use_container_width=True)
        except Exception as exc:
            st.info(f"Ensemble weights: {exc}")

    # ── Tab 4: Pipeline Jobs ──────────────────────────────────────────────────
    with tab_pipeline:
        st.subheader("⚙️ Stato Job Pipeline")
        try:
            from shared.db.duckdb_client import get_duckdb_client
            db = get_duckdb_client()
            jobs = [
                ("Composite Signal v3",   "SELECT computed_at FROM engine_composite_signal ORDER BY computed_at DESC LIMIT 1"),
                ("VIX Strategy",          "SELECT computed_at FROM vix_strategy_outputs ORDER BY computed_at DESC LIMIT 1"),
                ("Claims Inflation",      "SELECT computed_at FROM claims_inflation_signals ORDER BY computed_at DESC LIMIT 1"),
                ("Yield Curve",           "SELECT snapshot_date FROM yield_curve_snapshots ORDER BY snapshot_date DESC LIMIT 1"),
                ("Credit Spreads",        "SELECT computed_at FROM credit_spread_signals ORDER BY computed_at DESC LIMIT 1"),
                ("Economic Surprise",     "SELECT MAX(computed_at) FROM economic_surprise_results"),
                ("News Signal",           "SELECT MAX(signal_date) FROM news_signal"),
                ("IB Forecast",           "SELECT MAX(fetched_at) FROM ib_forecasts"),
                ("Valuation Signal",      "SELECT MAX(signal_date) FROM valuation_signal"),
                ("Labour Forecasts",      "SELECT MAX(generated_at) FROM labour_forecasts"),
            ]
            for job_name, sql in jobs:
                try:
                    rows = db.query(sql)
                    val = rows[0][0] if rows and rows[0][0] else None
                    icon = "🟢" if val else "🟡"
                    st.markdown(f"{icon} **{job_name}**: {val or 'nessun dato'}")
                except Exception:
                    st.markdown(f"🔴 **{job_name}**: errore query")
        except Exception as exc:
            st.error(f"DB non raggiungibile: {exc}")
        st.divider()
        st.info("Per avviare la pipeline: `poetry run python scripts/run_scheduler.py`")

    # ── Tab 5: Walk-Forward ───────────────────────────────────────────────────
    with tab_wf:
        st.subheader("🧪 Walk-Forward Validation — Out-of-Sample Sharpe")
        st.caption("OOS Sharpe > 0.5 su tutti i folds → strategia robusta.")
        col_l, col_r = st.columns([1, 2])
        with col_l:
            wf_ticker   = st.selectbox("Ticker", ["SPY", "QQQ", "GLD", "TLT"], key="s1_wf_ticker")
            wf_strategy = st.selectbox("Strategia", ["MA Cross (20/50)", "RSI (14)", "Momentum (20)"], key="s1_wf_strat")
            wf_folds    = st.slider("Folds", 3, 8, 5, key="s1_wf_folds")
            run_wf      = st.button("▶ Esegui", key="s1_wf_run")
        with col_r:
            if run_wf:
                with st.spinner("Walk-forward in corso..."):
                    try:
                        import yfinance as yf
                        import plotly.graph_objects as go
                        from engine.strategy_lab.walk_forward_validator import WalkForwardValidator
                        from engine.backtesting.strategies.ma_cross import MovingAverageCrossover
                        from engine.backtesting.strategies.rsi import RSIStrategy
                        from engine.backtesting.strategies.momentum import MomentumStrategy

                        hist = yf.Ticker(wf_ticker).history(period="3y")
                        if hist.empty or len(hist) < 120:
                            st.error("Dati insufficienti.")
                        else:
                            hist.index = hist.index.tz_localize(None)
                            df = hist[["Open","High","Low","Close","Volume"]].rename(columns=str.lower)
                            strat = {"MA Cross (20/50)": MovingAverageCrossover(20,50), "RSI (14)": RSIStrategy(14), "Momentum (20)": MomentumStrategy(20)}[wf_strategy]
                            result = WalkForwardValidator(n_splits=wf_folds).validate(df, strat)
                            c1, c2, c3 = st.columns(3)
                            c1.metric("OOS Sharpe medio", f"{result.mean_oos_sharpe:.3f}")
                            c2.metric("Std Sharpe", f"{result.std_oos_sharpe:.3f}")
                            c3.metric("Folds positivi", f"{result.pct_positive_folds*100:.0f}%")
                            fig_wf = go.Figure(go.Bar(
                                x=[f"Fold {i+1}" for i in range(len(result.fold_sharpes))],
                                y=result.fold_sharpes,
                                marker_color=["#10B981" if s>0 else "#EF4444" for s in result.fold_sharpes],
                                text=[f"{s:.2f}" for s in result.fold_sharpes], textposition="outside",
                            ))
                            fig_wf.add_hline(y=0.5, line_dash="dash", line_color="green")
                            fig_wf.update_layout(
                                height=240, margin=dict(l=0,r=0,t=20,b=0),
                                plot_bgcolor=tokens.bg_secondary, paper_bgcolor=tokens.bg_secondary,
                                font=dict(color=tokens.text_primary), yaxis_title="OOS Sharpe",
                            )
                            st.plotly_chart(fig_wf, use_container_width=True)
                    except Exception as exc:
                        st.error(f"Errore: {exc}")
            else:
                st.info("Seleziona parametri e clicca **▶ Esegui**.")
