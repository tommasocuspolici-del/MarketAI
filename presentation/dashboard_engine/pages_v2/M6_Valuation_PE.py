# ruff: noqa: N999
"""M6 — Valuation & PE Analysis ★ NUOVO (v8.2 — Blocco 3).

Dashboard valuation: P/E trailing, P/E forward, Shiller CAPE, ERP.
Legge da valuation_signal e pe_metrics (migration 018).
"""
from __future__ import annotations

__version__ = "8.2.0"
__all__ = ["body_m6_valuation_pe"]


def body_m6_valuation_pe(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    st.title("📊 Valuation — P/E & CAPE")
    cols_top = st.columns([4, 1])
    with cols_top[1]:
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
                "SELECT pe_trailing, pe_forward, cape, erp_implied, pe_date "
                "FROM pe_metrics ORDER BY pe_date DESC LIMIT 1"
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
        st.subheader("Storia P/E e CAPE (20 anni)")
        try:
            import pandas as pd
            import plotly.graph_objects as go

            rows = db.query(
                "SELECT pe_date, pe_trailing, pe_forward, cape "
                "FROM pe_metrics ORDER BY pe_date ASC LIMIT 5000"
            )
            if not rows:
                st.info("Nessuna storia disponibile.")
            else:
                df = pd.DataFrame(rows, columns=["date", "trailing", "forward", "cape"])
                df["date"] = pd.to_datetime(df["date"])

                fig = go.Figure()
                if df["trailing"].notna().any():
                    fig.add_trace(go.Scatter(
                        x=df["date"], y=df["trailing"],
                        name="Trailing P/E", mode="lines",
                        line=dict(color=tokens.colors.positive, width=1.8),
                    ))
                if df["forward"].notna().any():
                    fig.add_trace(go.Scatter(
                        x=df["date"], y=df["forward"],
                        name="Forward P/E", mode="lines",
                        line=dict(color=tokens.colors.info, width=1.5, dash="dot"),
                    ))
                if df["cape"].notna().any():
                    fig.add_trace(go.Scatter(
                        x=df["date"], y=df["cape"],
                        name="Shiller CAPE", mode="lines",
                        line=dict(color=tokens.colors.warning, width=2),
                    ))
                fig.update_layout(
                    height=400, title="P/E Ratios — Storia",
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    legend=dict(orientation="h", y=1.1),
                    margin=dict(l=0, r=0, t=40, b=0),
                )
                st.plotly_chart(fig, use_container_width=True)
        except Exception as exc:
            st.warning(f"Grafico storia non disponibile: {exc}")

        st.divider()
        st.subheader("Z-Score vs 20Y (contestualizzazione storica)")
        try:
            rows = db.query(
                "SELECT pe_date, zscore_trailing, zscore_forward, zscore_cape "
                "FROM pe_metrics WHERE zscore_trailing IS NOT NULL "
                "ORDER BY pe_date ASC LIMIT 5000"
            )
            if rows:
                import pandas as pd
                import plotly.graph_objects as go
                df = pd.DataFrame(rows, columns=["date", "z_trailing", "z_forward", "z_cape"])
                df["date"] = pd.to_datetime(df["date"])
                fig = go.Figure()
                for col, label, color in [
                    ("z_trailing", "Z Trailing PE", tokens.colors.positive),
                    ("z_forward",  "Z Forward PE",  tokens.colors.info),
                    ("z_cape",     "Z CAPE",         tokens.colors.warning),
                ]:
                    if df[col].notna().any():
                        fig.add_trace(go.Scatter(
                            x=df["date"], y=df[col],
                            name=label, mode="lines",
                            line=dict(color=color, width=1.5),
                        ))
                fig.add_hline(y=2.0, line_color="red", line_dash="dash", opacity=0.5)
                fig.add_hline(y=-2.0, line_color="green", line_dash="dash", opacity=0.5)
                fig.add_hline(y=0.0, line_color="gray", line_dash="dot", opacity=0.3)
                fig.update_layout(
                    height=300, title="Z-Score vs 20Y Media",
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=0, r=0, t=40, b=0),
                )
                st.plotly_chart(fig, use_container_width=True)
                st.caption("Linee rosse: ±2σ (estremo). Area grigia: fair value.")
        except Exception as exc:
            st.caption(f"Z-score non disponibile: {exc}")

    # ── Tab 3: Equity Risk Premium ─────────────────────────────────────────
    with tab_erp:
        st.subheader("Equity Risk Premium Implicito")
        st.caption("ERP = Earnings Yield (1/PE) − Risk Free Rate (TY10)")
        try:
            import pandas as pd
            import plotly.graph_objects as go
            rows = db.query(
                "SELECT pe_date, erp_implied FROM pe_metrics "
                "WHERE erp_implied IS NOT NULL ORDER BY pe_date ASC LIMIT 5000"
            )
            if not rows:
                st.info("ERP non disponibile — verificare TY10 in yield_curve_snapshots.")
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
        try:
            rows = db.query(
                "SELECT signal_date, valuation_score, trailing_pe_signal, "
                "forward_pe_signal, cape_signal, erp_signal, label "
                "FROM valuation_signal ORDER BY signal_date DESC LIMIT 90"
            )
            if not rows:
                st.info("Storico segnali non disponibile.")
            else:
                import pandas as pd
                import plotly.graph_objects as go
                df = pd.DataFrame(rows, columns=[
                    "date", "score", "t_pe", "f_pe", "cape", "erp", "label"
                ])
                df["date"] = pd.to_datetime(df["date"])

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df["date"], y=df["score"],
                    name="Valuation Score", mode="lines+markers",
                    line=dict(color=tokens.colors.primary, width=2),
                    marker=dict(size=4),
                ))
                for col, label, color in [
                    ("t_pe",  "Trailing PE",  tokens.colors.positive),
                    ("f_pe",  "Forward PE",   tokens.colors.info),
                    ("cape",  "CAPE",         tokens.colors.warning),
                    ("erp",   "ERP",          tokens.colors.neutral),
                ]:
                    fig.add_trace(go.Scatter(
                        x=df["date"], y=df[col],
                        name=label, mode="lines",
                        line=dict(color=color, width=1, dash="dot"),
                        opacity=0.7,
                    ))
                fig.add_hline(y=0, line_color="gray", line_dash="dot", opacity=0.3)
                fig.update_layout(
                    height=400, title="Segnale Valuation [-1, +1]",
                    yaxis=dict(range=[-1.1, 1.1]),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    legend=dict(orientation="h", y=1.1),
                    margin=dict(l=0, r=0, t=40, b=0),
                )
                st.plotly_chart(fig, use_container_width=True)

                st.caption(
                    "**Peso nel Composite v2.1:** 12% · "
                    "Score > 0 = mercato economico rispetto alla storia · "
                    "Score < 0 = mercato costoso"
                )
        except Exception as exc:
            st.warning(f"Storico segnali non disponibile: {exc}")
