# ruff: noqa: N999
"""M3 — Labour Market ★ aggiornato v8.3 (Blocco 1).

4 tab:
  1. JOLTS       — Openings, Hires, Quits, Beveridge gap
  2. Claims      — Initial/Continuing Claims + 4wk MA + regime
  3. Payrolls    — NFP per settore + cyclical/defensive split
  4. Regime      — Classificazione sintetica + recession probability
"""
from __future__ import annotations

__version__ = "8.3.0"
__all__ = ["body_m3_labour_market"]


def body_m3_labour_market(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    st.title("🌍 Labour Market — JOLTS · Claims · Payrolls · Regime")
    st.caption("FRED data · Classificazione 4 regimi · Forecast engine integrato")

    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
    except Exception as exc:
        st.error(f"DB non disponibile: {exc}")
        return

    tab_jolts, tab_claims, tab_payroll, tab_regime = st.tabs([
        "🏭 JOLTS",
        "📋 Claims",
        "💼 Payrolls",
        "🎭 Regime",
    ])

    # ── Tab 1: JOLTS ─────────────────────────────────────────────────────────
    with tab_jolts:
        st.subheader("JOLTS — Job Openings, Hires, Quits")
        try:
            import pandas as pd
            rows = db.query(
                "SELECT series_date, job_openings, hires, quits, layoffs_discharges, "
                "quits_rate, openings_rate, beveridge_gap, hires_quits_ratio "
                "FROM jolts_monthly ORDER BY series_date DESC LIMIT 24"
            )
            if not rows:
                st.info(
                    "Nessun dato JOLTS disponibile. "
                    "Configurare FRED_API_KEY e eseguire JOLTSFetcher."
                )
            else:
                latest = rows[0]
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    v = latest[1]
                    st.metric("Job Openings", f"{v:,.0f}K" if v else "N/A")
                with c2:
                    v = latest[5]
                    st.metric("Quits Rate", f"{v:.2f}%" if v else "N/A",
                              help="> 2.5% = workers confident, economia forte")
                with c3:
                    v = latest[6]
                    st.metric("Openings Rate", f"{v:.2f}%" if v else "N/A")
                with c4:
                    v = latest[7]
                    color = "🟢" if (v and v > 0) else "🔴"
                    st.metric(f"{color} Beveridge Gap", f"{v:+.2f}pp" if v else "N/A",
                              help="Openings Rate − Unemployment Rate: > 0 = mercato tight")

                st.divider()
                df = pd.DataFrame(rows, columns=[
                    "Data", "Openings_K", "Hires_K", "Quits_K", "Layoffs_K",
                    "Quits_Rate", "Openings_Rate", "Beveridge_Gap", "Hires_Quits_Ratio"
                ])
                df = df.sort_values("Data")
                st.line_chart(
                    df.set_index("Data")[["Quits_Rate", "Openings_Rate"]],
                    height=250
                )
                st.caption("Quits Rate e Openings Rate (%) — fonte FRED JTSQUR / JTSJOR")

                st.subheader("Hires vs Quits (K)")
                st.line_chart(
                    df.set_index("Data")[["Hires_K", "Quits_K"]],
                    height=200
                )
        except Exception as exc:
            st.warning(f"JOLTS non disponibili: {exc}")

    # ── Tab 2: Claims ─────────────────────────────────────────────────────────
    with tab_claims:
        st.subheader("Initial Claims — Settimanali e 4-Week MA")
        try:
            import pandas as pd
            rows = db.query(
                "SELECT week_ending, initial_claims, continuing_claims, "
                "claims_4wk_ma, claims_yoy_pct, cycle_regime, signal_strength "
                "FROM claims_cycle ORDER BY week_ending DESC LIMIT 52"
            )
            if not rows:
                st.info(
                    "Nessun dato Claims disponibile. "
                    "Eseguire ClaimsFetcher."
                )
            else:
                latest = rows[0]
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    v = latest[1]
                    st.metric("Initial Claims", f"{v:,.0f}K" if v else "N/A")
                with c2:
                    v = latest[3]
                    st.metric("4-Week MA", f"{v:,.0f}K" if v else "N/A")
                with c3:
                    v = latest[4]
                    delta_color = "inverse" if (v and v > 10) else "normal"
                    st.metric("YoY %", f"{v:+.1f}%" if v else "N/A",
                              delta_color=delta_color)
                with c4:
                    regime = latest[5] or "N/A"
                    regime_icons = {"expansion": "🟢", "peak": "🟡",
                                    "trough": "🟠", "contraction": "🔴"}
                    icon = regime_icons.get(regime, "❓")
                    st.metric(f"{icon} Regime", regime.capitalize())

                df = pd.DataFrame(rows, columns=[
                    "Data", "Initial_Claims", "Continuing_Claims",
                    "MA_4wk", "YoY_pct", "Regime", "Signal"
                ])
                df = df.sort_values("Data")
                st.line_chart(
                    df.set_index("Data")[["Initial_Claims", "MA_4wk"]],
                    height=250
                )
                st.caption("Initial Claims (K) e 4-Week MA — fonte FRED ICSA")
        except Exception as exc:
            st.warning(f"Claims non disponibili: {exc}")

    # ── Tab 3: Payrolls ───────────────────────────────────────────────────────
    with tab_payroll:
        st.subheader("Non-Farm Payrolls per Settore")
        try:
            import pandas as pd
            rows = db.query(
                "SELECT release_date, sector, jobs_added_k, yoy_pct, share_of_total, "
                "is_cyclical "
                "FROM payroll_sector "
                "WHERE release_date >= CURRENT_DATE - INTERVAL 13 MONTH "
                "ORDER BY release_date DESC, sector"
            )
            if not rows:
                st.info(
                    "Nessun dato Payroll disponibile. "
                    "Eseguire PayrollFetcher."
                )
            else:
                df = pd.DataFrame(rows, columns=[
                    "Data", "Settore", "Jobs_K", "YoY_%", "Share_%", "Ciclico"
                ])
                latest_date = df["Data"].max()
                latest = df[df["Data"] == latest_date]

                col_cyc, col_def = st.columns(2)
                with col_cyc:
                    st.markdown("**🔄 Settori Ciclici**")
                    cyc = latest[latest["Ciclico"] == True].sort_values("Jobs_K", ascending=False)
                    for _, row in cyc.iterrows():
                        v = row["Jobs_K"]
                        arrow = "▲" if (v and v > 0) else "▼"
                        st.write(f"{arrow} **{row['Settore']}**: {v:+.0f}K" if v else f"**{row['Settore']}**: N/A")
                with col_def:
                    st.markdown("**🛡️ Settori Difensivi**")
                    dfn = latest[latest["Ciclico"] != True].sort_values("Jobs_K", ascending=False)
                    for _, row in dfn.iterrows():
                        v = row["Jobs_K"]
                        arrow = "▲" if (v and v > 0) else "▼"
                        st.write(f"{arrow} **{row['Settore']}**: {v:+.0f}K" if v else f"**{row['Settore']}**: N/A")

                st.divider()
                total = df[df["Settore"] == "total_nonfarm"].sort_values("Data")
                if not total.empty:
                    st.subheader("Total NFP — Jobs Added (K)")
                    st.bar_chart(total.set_index("Data")["Jobs_K"], height=220)

        except Exception as exc:
            st.warning(f"Payroll non disponibili: {exc}")

    # ── Tab 4: Regime ─────────────────────────────────────────────────────────
    with tab_regime:
        st.subheader("Regime Mercato del Lavoro")
        try:
            import pandas as pd
            rows = db.query(
                "SELECT snapshot_date, regime, composite_score, jolts_score, "
                "claims_score, payroll_score, confidence "
                "FROM labour_regime ORDER BY snapshot_date DESC LIMIT 1"
            )
            if not rows:
                st.info(
                    "Nessun dato regime disponibile. "
                    "Eseguire LabourRegimeClassifier."
                )
            else:
                r = rows[0]
                regime_map = {
                    "tight":         ("🔥", "Mercato molto teso — pressioni inflazionistiche"),
                    "balanced":      ("✅", "Mercato equilibrato — crescita sostenibile"),
                    "slack":         ("⚠️", "Sottoutilizzo della forza lavoro"),
                    "deteriorating": ("🚨", "Deterioramento in atto — warning pre-recessivo"),
                }
                regime = r[1] or "unknown"
                icon, desc = regime_map.get(regime, ("❓", ""))
                score = r[2]

                st.metric(
                    f"{icon} Regime Corrente: {regime.upper()}",
                    f"Score: {score:+.3f}" if score is not None else "N/A",
                )
                st.info(desc)

                c1, c2, c3, c4 = st.columns(4)
                labels_vals = [("JOLTS", r[3]), ("Claims", r[4]),
                               ("Payroll", r[5]), ("Confidence", r[6])]
                for col, (label, val) in zip([c1, c2, c3, c4], labels_vals):
                    with col:
                        if label == "Confidence":
                            st.metric(label, f"{val:.1%}" if val else "N/A")
                        else:
                            st.metric(label, f"{val:+.3f}" if val else "N/A")

                st.divider()
                hist = db.query(
                    "SELECT snapshot_date, composite_score "
                    "FROM labour_regime ORDER BY snapshot_date DESC LIMIT 52"
                )
                if hist and len(hist) >= 4:
                    df_h = pd.DataFrame(hist, columns=["Data", "Score"])
                    df_h = df_h.sort_values("Data").set_index("Data")
                    st.line_chart(df_h["Score"], height=220)
                    st.caption("Composite Labour Score [-1,+1] — 52 settimane")

        except Exception as exc:
            st.warning(f"Regime non disponibile: {exc}")
