# ruff: noqa: N999
"""M5 — Economic Surprise Index ★ NUOVO (v8.3 — Blocco 2).

Dashboard Economic Surprise:
  Tab 1: ESI Composite  — score [-1,+1] + breakdown 4 settori
  Tab 2: Indicators     — tabella 20 indicatori con z-score
  Tab 3: Momentum       — trend EMA sorprese ultime 12 settimane
  Tab 4: Segnale        — contributo ESI al Composite Signal v2
"""
from __future__ import annotations

__version__ = "8.3.0"
__all__ = ["body_m5_economic_surprise"]


def body_m5_economic_surprise(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    st.title("⚡ Economic Surprise Index")
    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="m5v2_refresh"):
            st.cache_data.clear()
            st.rerun()
    st.caption("Citigroup CESI-style · 20 indicatori · 4 settori · z-score normalizzato")

    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
    except Exception as exc:
        st.error(f"DB non disponibile: {exc}")
        return

    tab_esi, tab_indicators, tab_momentum, tab_signal = st.tabs([
        "📊 ESI Composite",
        "📋 Indicatori",
        "📈 Momentum",
        "⚡ Segnale",
    ])

    # ── Tab 1: ESI Composite ─────────────────────────────────────────────────
    with tab_esi:
        st.subheader("Economic Surprise Index — Score Composito")
        try:
            rows = db.query(
                "SELECT index_date, esi_composite, esi_signal, "
                "labour_weight, growth_weight, inflation_weight, housing_weight "
                "FROM economic_surprise_index ORDER BY index_date DESC LIMIT 1"
            )
            if not rows:
                st.info("Nessun dato ESI disponibile. Eseguire SurpriseSignalGenerator.")
            else:
                r = rows[0]
                esi = r[1]
                color = "🟢" if esi and esi > 0.1 else ("🔴" if esi and esi < -0.1 else "🟡")
                st.metric(
                    f"{color} ESI Composite",
                    f"{esi:+.3f}" if esi is not None else "N/A",
                    help="[-1,+1]: +1 = economia sorprende positivamente su tutti i fronti",
                )
                st.caption(f"Data: {r[0]}")
        except Exception as exc:
            st.warning(f"ESI non disponibile: {exc}")

        st.divider()

        # Sector scores
        st.subheader("Score per Settore")
        sectors = ["labour", "growth", "inflation", "housing"]
        sector_icons = {"labour": "👷", "growth": "📈", "inflation": "🔥", "housing": "🏠"}
        try:
            cols = st.columns(4)
            for col, sector in zip(cols, sectors):
                rows_s = db.query(
                    "SELECT score_ema, direction FROM surprise_sector_score "
                    "WHERE sector=? ORDER BY score_date DESC LIMIT 1",
                    [sector],
                )
                with col:
                    if rows_s:
                        score = rows_s[0][0]
                        direction = rows_s[0][1] or "stable"
                        arrow = "▲" if direction == "improving" else ("▼" if direction == "deteriorating" else "→")
                        st.metric(
                            f"{sector_icons.get(sector, '')} {sector.capitalize()}",
                            f"{score:+.3f}" if score is not None else "N/A",
                            delta=arrow,
                        )
                    else:
                        st.metric(f"{sector_icons.get(sector, '')} {sector.capitalize()}", "N/A")
        except Exception as exc:
            st.warning(f"Score settoriali non disponibili: {exc}")

    # ── Tab 2: Indicatori ────────────────────────────────────────────────────
    with tab_indicators:
        st.subheader("Ultimi Z-Score per Indicatore")
        try:
            import pandas as pd
            rows = db.query(
                "SELECT indicator_code, sector, actual_value, consensus_value, "
                "surprise_raw, z_score, release_date "
                "FROM economic_surprise "
                "WHERE release_date >= CURRENT_DATE - INTERVAL 90 DAY "
                "ORDER BY ABS(z_score) DESC NULLS LAST LIMIT 30"
            )
            if not rows:
                st.info("Nessun dato disponibile.")
            else:
                df = pd.DataFrame(rows, columns=[
                    "Indicatore", "Settore", "Actual", "Consensus",
                    "Surprise", "Z-Score", "Data"
                ])
                df["Z-Score"] = df["Z-Score"].round(2)
                df["Surprise"] = df["Surprise"].round(3)

                def _z_color(z):
                    if z is None or pd.isna(z):
                        return ""
                    if z > 2:
                        return "background-color: #1a7a4a22"
                    if z < -2:
                        return "background-color: #7a1a1a22"
                    return ""

                st.dataframe(
                    df.style.applymap(_z_color, subset=["Z-Score"]),
                    use_container_width=True,
                    hide_index=True,
                )
        except Exception as exc:
            st.warning(f"Indicatori non disponibili: {exc}")

    # ── Tab 3: Momentum ──────────────────────────────────────────────────────
    with tab_momentum:
        st.subheader("Momentum ESI — Score EMA 12 Settimane")
        try:
            import pandas as pd
            rows = db.query(
                "SELECT score_date, sector, score_ema, score_momentum, direction "
                "FROM surprise_sector_score "
                "WHERE score_date >= CURRENT_DATE - INTERVAL 90 DAY "
                "ORDER BY score_date, sector"
            )
            if not rows:
                st.info("Nessun dato momentum disponibile.")
            else:
                df = pd.DataFrame(rows, columns=["Data", "Settore", "EMA", "Momentum", "Direzione"])
                for sector in sectors:
                    sub = df[df["Settore"] == sector]
                    if not sub.empty:
                        st.line_chart(sub.set_index("Data")["EMA"], height=150)
                        st.caption(f"{sector_icons.get(sector, '')} {sector.capitalize()}")
        except Exception as exc:
            st.warning(f"Momentum non disponibile: {exc}")

    # ── Tab 4: Segnale ───────────────────────────────────────────────────────
    with tab_signal:
        st.subheader("Contributo ESI al Composite Signal v2")
        try:
            import pandas as pd
            rows = db.query(
                "SELECT index_date, esi_composite, esi_signal "
                "FROM economic_surprise_index "
                "ORDER BY index_date DESC LIMIT 52"
            )
            if not rows:
                st.info("Nessun dato segnale disponibile.")
            else:
                df = pd.DataFrame(rows, columns=["Data", "ESI", "Segnale"])
                df = df.sort_values("Data")
                st.line_chart(df.set_index("Data")[["ESI", "Segnale"]], height=300)
                st.caption(
                    "**ESI** = score composito grezzo · "
                    "**Segnale** = ESI normalizzato per Composite Signal v2"
                )
        except Exception as exc:
            st.warning(f"Segnale non disponibile: {exc}")
