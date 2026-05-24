# ruff: noqa: N999
"""M6 — Valuation & PE Analysis ★ NUOVO (v8.5 — Blocco 3).

Dashboard valuation: P/E trailing, P/E forward, Shiller CAPE, ERP.
Storia CAPE e ERP da shiller_cape_historical (Yale dataset, 1996+).
Tab Storia/ERP/Segnale leggono dallo storico (non da pe_metrics che è snapshot).
v8.5: Overview con fallback ERP da shiller_cape_historical; chart CAPE Signal
ridisegnato con subplot CAPE/ERP, area fill conditional verde/rosso e KPI.
"""
from __future__ import annotations

__version__ = "8.5.0"
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
            # Fallback: pe_metrics ha CAPE ma quasi sempre NULL su trailing/forward/erp
            # (no fundamentals provider per ^GSPC). Riempi da shiller_cape_historical.
            cape_val = rows[0][2] if rows else None
            erp_val  = rows[0][3] if rows else None
            metric_dt = rows[0][4] if rows else None
            shiller_fallback_dt = None
            if cape_val is None or erp_val is None:
                try:
                    hist = db.query(
                        "SELECT data_date, cape_ratio, erp_implied "
                        "FROM shiller_cape_historical "
                        "WHERE cape_ratio IS NOT NULL "
                        "ORDER BY data_date DESC LIMIT 1"
                    )
                    if hist:
                        h = hist[0]
                        if cape_val is None:
                            cape_val = h[1]
                        if erp_val is None:
                            erp_val = h[2]
                        shiller_fallback_dt = h[0]
                except Exception:
                    pass

            if not rows and cape_val is None:
                st.info("Nessun dato PE disponibile. Premere 📥 Carica valuation.")
            else:
                trailing = rows[0][0] if rows else None
                forward  = rows[0][1] if rows else None
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    val = f"{trailing:.1f}x" if trailing else "N/A"
                    st.metric("Trailing P/E", val,
                              help="Richiede fundamentals provider (EDGAR/Alpha Vantage)")
                with c2:
                    val = f"{forward:.1f}x" if forward else "N/A"
                    st.metric("Forward P/E", val,
                              help="Richiede Alpha Vantage o IBES")
                with c3:
                    val = f"{cape_val:.1f}x" if cape_val else "N/A"
                    st.metric("Shiller CAPE", val,
                              help="Yale Shiller dataset (snapshot pe_metrics + storico)")
                with c4:
                    val = f"{erp_val*100:+.2f}%" if erp_val is not None else "N/A"
                    st.metric("ERP Implicito", val,
                              help="Earnings Yield (1/CAPE) − Bond Yield TY10")
                # Caption con source
                caption_parts = []
                if metric_dt:
                    caption_parts.append(f"Snapshot pe_metrics: {metric_dt}")
                if shiller_fallback_dt and (rows is None or rows[0][3] is None):
                    caption_parts.append(f"ERP da Shiller storico: {shiller_fallback_dt}")
                if caption_parts:
                    st.caption(" · ".join(caption_parts))
                if trailing is None and forward is None:
                    st.info(
                        "ℹ️ Trailing/Forward P/E richiedono fundamentals provider attivo "
                        "(EDGAR + Alpha Vantage). CAPE e ERP usano lo storico Shiller Yale."
                    )
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
            from plotly.subplots import make_subplots

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

                has_erp = df_h["erp_signal"].notna().any()
                rows_n = 2 if has_erp else 1
                row_heights = [0.58, 0.42] if has_erp else [1.0]
                titles: tuple[str, ...] = (
                    "CAPE Signal — z-score 20Y rolling",
                    "ERP Signal — Shiller earnings yield − bond yield",
                ) if has_erp else ("CAPE Signal — z-score 20Y rolling",)

                fig = make_subplots(
                    rows=rows_n, cols=1, shared_xaxes=True,
                    row_heights=row_heights, vertical_spacing=0.10,
                    subplot_titles=titles,
                )

                # CAPE: split positive (verde, economico) e negative (rosso, costoso)
                # per ottenere conditional fill verso lo zero.
                green_line  = "rgba(34,197,94,1)"
                green_fill  = "rgba(34,197,94,0.28)"
                red_line    = "rgba(239,68,68,1)"
                red_fill    = "rgba(239,68,68,0.28)"

                cape_pos = df_h["cape_signal"].where(df_h["cape_signal"] >= 0)
                cape_neg = df_h["cape_signal"].where(df_h["cape_signal"] < 0)
                fig.add_trace(go.Scatter(
                    x=df_h["date"], y=cape_pos,
                    name="CAPE economico (signal > 0)", mode="lines",
                    line=dict(color=green_line, width=1.6),
                    fill="tozeroy", fillcolor=green_fill,
                    hovertemplate="%{x|%b %Y}<br>signal: %{y:+.2f}<extra></extra>",
                ), row=1, col=1)
                fig.add_trace(go.Scatter(
                    x=df_h["date"], y=cape_neg,
                    name="CAPE costoso (signal < 0)", mode="lines",
                    line=dict(color=red_line, width=1.6),
                    fill="tozeroy", fillcolor=red_fill,
                    hovertemplate="%{x|%b %Y}<br>signal: %{y:+.2f}<extra></extra>",
                ), row=1, col=1)

                # Soglie ±0.5 e ±1.0 sul subplot CAPE
                for y_val, color, label in [
                    (1.0,  "rgba(34,197,94,0.45)",  "+1 max economico"),
                    (0.5,  "rgba(34,197,94,0.30)",  "+0.5 soglia"),
                    (-0.5, "rgba(239,68,68,0.30)",  "-0.5 soglia"),
                    (-1.0, "rgba(239,68,68,0.45)",  "-1 max costoso"),
                ]:
                    fig.add_hline(
                        y=y_val, line_color=color, line_dash="dash",
                        annotation_text=label, annotation_position="right",
                        annotation_font_size=10, opacity=0.7, row=1, col=1,
                    )
                fig.add_hline(y=0, line_color="gray", line_dash="dot",
                              opacity=0.5, row=1, col=1)

                # ERP subplot (se disponibile)
                if has_erp:
                    erp_pos = df_h["erp_signal"].where(df_h["erp_signal"] >= 0)
                    erp_neg = df_h["erp_signal"].where(df_h["erp_signal"] < 0)
                    fig.add_trace(go.Scatter(
                        x=df_h["date"], y=erp_pos,
                        name="ERP attraente (premio > 2%)", mode="lines",
                        line=dict(color=green_line, width=1.4),
                        fill="tozeroy", fillcolor=green_fill,
                        hovertemplate="%{x|%b %Y}<br>signal: %{y:+.2f}<extra></extra>",
                        showlegend=True,
                    ), row=2, col=1)
                    fig.add_trace(go.Scatter(
                        x=df_h["date"], y=erp_neg,
                        name="ERP debole (bond preferiti)", mode="lines",
                        line=dict(color=red_line, width=1.4),
                        fill="tozeroy", fillcolor=red_fill,
                        hovertemplate="%{x|%b %Y}<br>signal: %{y:+.2f}<extra></extra>",
                        showlegend=True,
                    ), row=2, col=1)
                    fig.add_hline(y=0, line_color="gray", line_dash="dot",
                                  opacity=0.5, row=2, col=1)
                    fig.update_yaxes(range=[-1.15, 1.15], row=2, col=1,
                                     gridcolor="rgba(128,128,128,0.15)",
                                     zeroline=False, title_text="signal")

                fig.update_yaxes(range=[-1.15, 1.15], row=1, col=1,
                                 gridcolor="rgba(128,128,128,0.15)",
                                 zeroline=False, title_text="signal")
                fig.update_xaxes(gridcolor="rgba(128,128,128,0.15)", zeroline=False)
                fig.update_layout(
                    height=560 if has_erp else 380,
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    legend=dict(orientation="h", y=1.10, x=0,
                                bgcolor="rgba(0,0,0,0)"),
                    margin=dict(l=10, r=70, t=70, b=10),
                    hovermode="x unified",
                )
                st.plotly_chart(fig, use_container_width=True)

                # KPI riassuntivi sotto al chart
                last_cape_sig = df_h["cape_signal"].dropna()
                last_erp_sig  = df_h["erp_signal"].dropna()
                k1, k2, k3 = st.columns(3)
                with k1:
                    if not last_cape_sig.empty:
                        v = float(last_cape_sig.iloc[-1])
                        st.metric("CAPE Signal corrente", f"{v:+.2f}",
                                  help="Ultimo valore nello storico Shiller "
                                       "(z-score rolling 20Y)")
                with k2:
                    if not last_erp_sig.empty:
                        v = float(last_erp_sig.iloc[-1])
                        st.metric("ERP Signal corrente", f"{v:+.2f}")
                with k3:
                    if not last_cape_sig.empty:
                        pct_neg = float((last_cape_sig < 0).mean() * 100)
                        st.metric("% storico costoso", f"{pct_neg:.0f}%",
                                  help="Quota di mesi in cui CAPE signal < 0")

                st.caption(
                    "**Peso nel Composite v2.1:** 12% · "
                    "🟢 signal > 0 = mercato economico vs 20Y · "
                    "🔴 signal < 0 = mercato costoso · "
                    "Soglie operative ±0.5 (linee tratteggiate)."
                )
        except Exception as exc:
            st.warning(f"Storico segnale non disponibile: {exc}")
