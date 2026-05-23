# ruff: noqa: N999
"""M6 — Valuation & PE Analysis ★ NUOVO (v8.4 — Blocco 3).

Dashboard valuation: P/E trailing, P/E forward, Shiller CAPE, ERP.
Storia CAPE e ERP da shiller_cape_historical (Yale dataset, 1996+).
Tab Storia/ERP/Segnale leggono dallo storico (non da pe_metrics che è snapshot).
"""
from __future__ import annotations

__version__ = "8.4.0"
__all__ = ["body_m6_valuation_pe"]


def _run_valuation_pipeline() -> dict:  # pragma: no cover
    """Carica CAPE Shiller da Yale/FRED e calcola segnale valuation per ^GSPC."""
    result: dict = {"cape_rows": 0, "signal_ok": False, "error": None}
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
    except Exception as exc:
        result["error"] = f"DB: {exc}"
        return result

    try:
        from engine.analytics.valuation.shiller_cape_fetcher import ShillerCAPEFetcher
        result["cape_rows"] = ShillerCAPEFetcher(client=db).fetch_and_persist(lookback_years=30)
    except Exception as exc:
        result["error"] = f"CAPE fetch: {str(exc)[:120]}"

    try:
        from engine.analytics.valuation.valuation_signal_generator import ValuationSignalGenerator
        ValuationSignalGenerator(client=db).compute("^GSPC")
        result["signal_ok"] = True
    except Exception as exc:
        err = f"Signal: {str(exc)[:120]}"
        result["error"] = f"{result['error']} | {err}" if result["error"] else err

    return result


def body_m6_valuation_pe(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    st.title("📊 Valuation — P/E & CAPE")
    cols_top = st.columns([3, 1, 1])
    with cols_top[1]:
        if st.button("📥 Carica valuation", key="m6_load"):
            with st.spinner("Caricamento CAPE Shiller e segnali..."):
                r = _run_valuation_pipeline()
            if r["signal_ok"] or r["cape_rows"] > 0:
                parts = []
                if r["cape_rows"] > 0:
                    parts.append(f"CAPE: {r['cape_rows']} righe")
                if r["signal_ok"]:
                    parts.append("Segnale ^GSPC calcolato")
                st.success(" · ".join(parts))
            else:
                st.error(f"Caricamento fallito: {r['error']}")
            st.cache_data.clear()
            st.rerun()
    with cols_top[2]:
        if st.button("🔄 Aggiorna", key="m6_refresh"):
            st.cache_data.clear()
            st.rerun()
    st.caption("Trailing P/E · Forward P/E · Shiller CAPE · Equity Risk Premium")

    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
    except Exception as exc:
        st.error(f"DB non disponibile: {exc}")
        return

    # ── Tab structure ──────────────────────────────────────────────────────
    tab_overview, tab_history, tab_erp, tab_signal = st.tabs([
        "📈 Overview",
        "📅 Storia PE/CAPE",
        "💰 Equity Risk Premium",
        "⚡ Segnale Composito",
    ])

    # ── Tab 1: Overview corrente ───────────────────────────────────────────
    with tab_overview:
        st.subheader("Metriche Valuation Correnti")
        try:
            rows = db.query(
                "SELECT trailing_pe, forward_pe, shiller_cape, erp_implied, metric_date "
                "FROM pe_metrics ORDER BY metric_date DESC LIMIT 1"
            )
            if not rows:
                st.info("Nessun dato PE disponibile. Eseguire il ValuationSignalGenerator.")
            else:
                r = rows[0]
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    val = f"{r[0]:.1f}x" if r[0] else "N/A"
                    st.metric("Trailing P/E", val)
                with c2:
                    val = f"{r[1]:.1f}x" if r[1] else "N/A"
                    st.metric("Forward P/E", val)
                with c3:
                    val = f"{r[2]:.1f}x" if r[2] else "N/A"
                    st.metric("Shiller CAPE", val)
                with c4:
                    val = f"{r[3]*100:.2f}%" if r[3] else "N/A"
                    st.metric("ERP Implicito", val)
                if r[4]:
                    st.caption(f"Dati al: {r[4]}")
        except Exception as exc:
            st.warning(f"PE metrics non disponibili: {exc}")

        st.divider()
        st.subheader("Segnale Valuation")
        try:
            rows = db.query(
                "SELECT valuation_score, label, trailing_pe_signal, forward_pe_signal, "
                "cape_signal, erp_signal, signal_date "
                "FROM valuation_signal ORDER BY signal_date DESC LIMIT 1"
            )
            if not rows:
                st.info("Segnale non ancora calcolato.")
            else:
                r = rows[0]
                score = r[0] or 0.0
                label = r[1] or "unknown"
                color = (tokens.colors.positive if score > 0.1
                         else tokens.colors.negative if score < -0.1
                         else tokens.colors.neutral)
                st.markdown(
                    f"<h2 style='color:{color};text-align:center'>"
                    f"{label.replace('_',' ').title()}&nbsp;&nbsp;{score:+.3f}</h2>",
                    unsafe_allow_html=True,
                )
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.metric("Trailing PE Signal", f"{r[2]:+.3f}" if r[2] else "N/A")
                with c2:
                    st.metric("Forward PE Signal", f"{r[3]:+.3f}" if r[3] else "N/A")
                with c3:
                    st.metric("CAPE Signal", f"{r[4]:+.3f}" if r[4] else "N/A")
                with c4:
                    st.metric("ERP Signal", f"{r[5]:+.3f}" if r[5] else "N/A")
                if r[6]:
                    st.caption(f"Calcolato il: {r[6]}")
        except Exception as exc:
            st.warning(f"Segnale non disponibile: {exc}")

    # ── Tab 2: Storia PE / CAPE ────────────────────────────────────────────
    with tab_history:
        st.subheader("Storia Shiller CAPE (da Yale dataset)")
        try:
            import pandas as pd
            import numpy as np
            import plotly.graph_objects as go

            rows = db.query(
                "SELECT data_date, cape_ratio FROM shiller_cape_historical "
                "WHERE cape_ratio IS NOT NULL ORDER BY data_date ASC"
            )
            if not rows:
                st.info("Nessuna storia CAPE disponibile. Premere 📥 Carica valuation.")
            else:
                df = pd.DataFrame(rows, columns=["date", "cape"])
                df["date"] = pd.to_datetime(df["date"])

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df["date"], y=df["cape"],
                    name="Shiller CAPE", mode="lines",
                    line=dict(color=tokens.colors.warning, width=2),
                ))
                # Reference lines: mean and ±1σ over full history
                cape_mean = float(df["cape"].mean())
                cape_std  = float(df["cape"].std())
                fig.add_hline(y=cape_mean, line_color="gray", line_dash="dot",
                              annotation_text=f"Media {cape_mean:.1f}x", opacity=0.5)
                fig.add_hline(y=cape_mean + cape_std, line_color="red", line_dash="dash",
                              annotation_text=f"+1σ {cape_mean+cape_std:.1f}x", opacity=0.4)
                fig.add_hline(y=cape_mean - cape_std, line_color="green", line_dash="dash",
                              annotation_text=f"-1σ {cape_mean-cape_std:.1f}x", opacity=0.4)
                fig.update_layout(
                    height=400,
                    title=f"Shiller CAPE — {df['date'].min().year}–{df['date'].max().year} ({len(df)} mesi)",
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    legend=dict(orientation="h", y=1.1),
                    margin=dict(l=0, r=0, t=40, b=0),
                )
                st.plotly_chart(fig, use_container_width=True)
                latest = df.iloc[-1]
                pct = (df["cape"] <= latest["cape"]).mean() * 100
                st.caption(
                    f"CAPE corrente: **{latest['cape']:.1f}x** "
                    f"(percentile {pct:.0f}° vs storia · media {cape_mean:.1f}x)"
                )
        except Exception as exc:
            st.warning(f"Grafico storia non disponibile: {exc}")

        st.divider()
        st.subheader("Z-Score CAPE rolling 20Y (contestualizzazione storica)")
        try:
            rows = db.query(
                "SELECT data_date, cape_ratio FROM shiller_cape_historical "
                "WHERE cape_ratio IS NOT NULL ORDER BY data_date ASC"
            )
            if rows:
                import pandas as pd
                import numpy as np
                import plotly.graph_objects as go
                df = pd.DataFrame(rows, columns=["date", "cape"])
                df["date"] = pd.to_datetime(df["date"])
                roll_mean = df["cape"].rolling(240, min_periods=60).mean()
                roll_std  = df["cape"].rolling(240, min_periods=60).std()
                df["z_cape"] = (df["cape"] - roll_mean) / roll_std.replace(0, np.nan)

                fig = go.Figure()
                if df["z_cape"].notna().any():
                    fig.add_trace(go.Scatter(
                        x=df["date"], y=df["z_cape"],
                        name="Z CAPE (20Y rolling)", mode="lines",
                        line=dict(color=tokens.colors.warning, width=1.8),
                    ))
                fig.add_hline(y=2.0, line_color="red", line_dash="dash", opacity=0.5,
                              annotation_text="+2σ estremo costoso")
                fig.add_hline(y=-2.0, line_color="green", line_dash="dash", opacity=0.5,
                              annotation_text="-2σ estremo economico")
                fig.add_hline(y=0.0, line_color="gray", line_dash="dot", opacity=0.3)
                fig.update_layout(
                    height=300, title="Z-Score CAPE vs Rolling 20Y",
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=0, r=0, t=40, b=0),
                )
                st.plotly_chart(fig, use_container_width=True)
                st.caption(
                    "Z > +2: estremamente costoso · Z < -2: estremamente economico · "
                    "calcolato su finestra rolling 240 mesi (20 anni)."
                )
        except Exception as exc:
            st.caption(f"Z-score non disponibile: {exc}")

    # ── Tab 3: Equity Risk Premium ─────────────────────────────────────────
    with tab_erp:
        st.subheader("Equity Risk Premium Implicito")
        st.caption("ERP = Earnings Yield (1/CAPE) − Bond Yield (TY10) · fonte: Shiller Yale")
        try:
            import pandas as pd
            import plotly.graph_objects as go
            rows = db.query(
                "SELECT data_date, erp_implied FROM shiller_cape_historical "
                "WHERE erp_implied IS NOT NULL ORDER BY data_date ASC"
            )
            if not rows:
                st.info("ERP non disponibile — premere 📥 Carica valuation per popolare shiller_cape_historical.")
            else:
                df = pd.DataFrame(rows, columns=["date", "erp"])
                df["date"] = pd.to_datetime(df["date"])
                df["erp_pct"] = df["erp"] * 100

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df["date"], y=df["erp_pct"],
                    fill="tozeroy", mode="lines",
                    line=dict(color=tokens.colors.positive, width=1.5),
                    fillcolor="rgba(0,200,100,0.15)",
                ))
                fig.add_hline(y=3.0, line_color="green", line_dash="dash",
                              annotation_text="ERP target 3%", opacity=0.7)
                fig.add_hline(y=0.0, line_color="red", line_dash="dot", opacity=0.4)
                fig.update_layout(
                    height=350, title="Equity Risk Premium (%)",
                    yaxis_ticksuffix="%",
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=0, r=0, t=40, b=0),
                )
                st.plotly_chart(fig, use_container_width=True)

                latest_erp = df["erp_pct"].iloc[-1]
                if latest_erp > 3.0:
                    st.success(f"ERP corrente: {latest_erp:.2f}% — Azionario attraente vs bond.")
                elif latest_erp > 0.0:
                    st.info(f"ERP corrente: {latest_erp:.2f}% — Premia modesto.")
                else:
                    st.warning(f"ERP corrente: {latest_erp:.2f}% — Bond più attraenti dell'azionario.")
        except Exception as exc:
            st.warning(f"ERP non disponibile: {exc}")

    # ── Tab 4: Segnale composito ────────────────────────────────────────────
    with tab_signal:
        st.subheader("Contributo Valuation al Composite Signal v2.1")

        # KPI: score corrente da valuation_signal
        try:
            sig_rows = db.query(
                "SELECT valuation_score, label, signal_date "
                "FROM valuation_signal ORDER BY signal_date DESC LIMIT 1"
            )
            if sig_rows:
                score = sig_rows[0][0] or 0.0
                label = sig_rows[0][1] or "unknown"
                color = (tokens.colors.positive if score > 0.1
                         else tokens.colors.negative if score < -0.1
                         else tokens.colors.neutral)
                st.markdown(
                    f"<h2 style='color:{color};text-align:center'>"
                    f"{label.replace('_',' ').title()}&nbsp;&nbsp;{score:+.3f}</h2>",
                    unsafe_allow_html=True,
                )
                st.caption(f"Calcolato il: {sig_rows[0][2]}")
            else:
                st.info("Segnale corrente non disponibile. Premere 📥 Carica valuation.")
        except Exception as exc:
            st.caption(f"Score non disponibile: {exc}")

        st.divider()

        # Storico CAPE signal da shiller_cape_historical (z-score rolling 20Y)
        st.subheader("CAPE Signal Storico (z-score 20Y rolling)")
        try:
            import pandas as pd
            import numpy as np
            import plotly.graph_objects as go

            hist_rows = db.query(
                "SELECT data_date, cape_ratio, erp_implied "
                "FROM shiller_cape_historical "
                "WHERE cape_ratio IS NOT NULL "
                "ORDER BY data_date ASC"
            )
            if not hist_rows:
                st.info("Nessun dato storico CAPE. Premere 📥 Carica valuation.")
            else:
                df_h = pd.DataFrame(hist_rows, columns=["date", "cape", "erp"])
                df_h["date"] = pd.to_datetime(df_h["date"])

                roll_mean = df_h["cape"].rolling(240, min_periods=60).mean()
                roll_std  = df_h["cape"].rolling(240, min_periods=60).std()
                df_h["cape_z"]      = (df_h["cape"] - roll_mean) / roll_std.replace(0, np.nan)
                df_h["cape_signal"] = df_h["cape_z"].apply(
                    lambda z: float(np.clip(-z / 2.0, -1, 1)) if pd.notna(z) else None
                )
                df_h["erp_signal"] = df_h["erp"].apply(
                    lambda e: float(np.clip((e - 0.02) / 0.02, -1, 1))
                    if pd.notna(e) and e is not None else None
                )

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df_h["date"], y=df_h["cape_signal"],
                    name="CAPE Signal", mode="lines",
                    line=dict(color=tokens.colors.warning, width=2),
                ))
                if df_h["erp_signal"].notna().any():
                    fig.add_trace(go.Scatter(
                        x=df_h["date"], y=df_h["erp_signal"],
                        name="ERP Signal (Shiller)", mode="lines",
                        line=dict(color=tokens.colors.positive, width=1.5, dash="dot"),
                        opacity=0.8,
                    ))
                fig.add_hline(y=0, line_color="gray", line_dash="dot", opacity=0.3)
                fig.add_hline(y=0.5,  line_color="green", line_dash="dash", opacity=0.3)
                fig.add_hline(y=-0.5, line_color="red",   line_dash="dash", opacity=0.3)
                fig.update_layout(
                    height=400,
                    title="CAPE Signal [-1, +1] — z-score rolling 20Y",
                    yaxis=dict(range=[-1.1, 1.1]),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    legend=dict(orientation="h", y=1.1),
                    margin=dict(l=0, r=0, t=40, b=0),
                )
                st.plotly_chart(fig, use_container_width=True)
                st.caption(
                    "**Peso nel Composite v2.1:** 12% · "
                    "Score > 0 = mercato economico rispetto alla storia 20Y · "
                    "Score < 0 = mercato costoso · "
                    "Linee tratteggiate: ±0.5 (soglie segnale)"
                )
        except Exception as exc:
            st.warning(f"Storico segnale non disponibile: {exc}")
