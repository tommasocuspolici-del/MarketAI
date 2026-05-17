# ruff: noqa: N999
"""Q10 — Economic Surprise Heatmap ★ NUOVO (v8.3 — Blocco 2).

Dashboard heatmap sorprese economiche:
  Tab 1: Heatmap 12M  — z-score per indicatore × mese (stile Bloomberg CESI)
  Tab 2: Z-Score live — tabella aggiornata con ranking
  Tab 3: Sector trend — EMA momentum per settore
"""
from __future__ import annotations

__version__ = "8.3.0"
__all__ = ["body_q10_surprise_heatmap"]

_SECTOR_ORDER = ["labour", "growth", "inflation", "housing", "trade_external"]
_SECTOR_ICONS = {
    "labour":         "👷",
    "growth":         "📈",
    "inflation":      "🔥",
    "housing":        "🏠",
    "trade_external": "🌍",
}


def body_q10_surprise_heatmap(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    st.title("🗺️ Economic Surprise — Heatmap")
    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="q10v2_refresh"):
            st.cache_data.clear()
            st.rerun()
    st.caption("Z-Score per Indicatore × Mese · Stile Bloomberg CESI · Ultimi 12 mesi")

    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
    except Exception as exc:
        st.error(f"DB non disponibile: {exc}")
        return

    tab_heatmap, tab_ranking, tab_sector = st.tabs([
        "🗺️ Heatmap 12M",
        "🏆 Z-Score Ranking",
        "📊 Sector Trend",
    ])

    # ── Tab 1: Heatmap ────────────────────────────────────────────────────────
    with tab_heatmap:
        st.subheader("Z-Score Sorprese — Ultimi 12 Mesi")
        try:
            import pandas as pd
            rows = db.query(
                "SELECT indicator_code, sector, z_score, release_date "
                "FROM economic_surprise "
                "WHERE release_date >= CURRENT_DATE - INTERVAL 365 DAY "
                "AND z_score IS NOT NULL "
                "ORDER BY release_date"
            )
            if not rows:
                st.info(
                    "Nessun dato disponibile. Configurare FRED_API_KEY e "
                    "eseguire il SurpriseCalculator."
                )
            else:
                df = pd.DataFrame(rows, columns=["Indicatore", "Settore", "Z-Score", "Data"])
                df["Mese"] = pd.to_datetime(df["Data"]).dt.to_period("M").astype(str)

                # Pivot: indicatori × mesi
                pivot = df.pivot_table(
                    index="Indicatore", columns="Mese",
                    values="Z-Score", aggfunc="last"
                ).round(2)

                # Color-coded dataframe
                def _color_zscore(val):
                    if pd.isna(val):
                        return ""
                    if val > 2.0:
                        return "background-color: #0d6e3a; color: white"
                    if val > 1.0:
                        return "background-color: #1a7a4a44"
                    if val < -2.0:
                        return "background-color: #6e0d0d; color: white"
                    if val < -1.0:
                        return "background-color: #7a1a1a44"
                    return ""

                st.dataframe(
                    pivot.style.applymap(_color_zscore),
                    use_container_width=True,
                    height=500,
                )
                st.caption(
                    "🟢 Z > +2 sorpresa molto positiva · "
                    "🔴 Z < -2 sorpresa molto negativa"
                )
        except Exception as exc:
            st.warning(f"Heatmap non disponibile: {exc}")

    # ── Tab 2: Z-Score Ranking ────────────────────────────────────────────────
    with tab_ranking:
        st.subheader("Ranking Z-Score — Ultimi 90 Giorni")

        sector_filter = st.selectbox(
            "Filtra per settore",
            ["tutti"] + _SECTOR_ORDER,
            format_func=lambda s: f"{_SECTOR_ICONS.get(s, '')} {s.capitalize()}" if s != "tutti" else "🌐 Tutti",
        )

        try:
            import pandas as pd
            query_where = (
                "WHERE release_date >= CURRENT_DATE - INTERVAL 90 DAY AND z_score IS NOT NULL"
            )
            params: list = []
            if sector_filter != "tutti":
                query_where += " AND sector=?"
                params.append(sector_filter)

            rows = db.query(
                f"SELECT indicator_code, sector, actual_value, consensus_value, "
                f"surprise_raw, z_score, release_date "
                f"FROM economic_surprise {query_where} "
                f"ORDER BY ABS(z_score) DESC NULLS LAST LIMIT 25",
                params or None,
            )
            if not rows:
                st.info("Nessun dato per il filtro selezionato.")
            else:
                df = pd.DataFrame(rows, columns=[
                    "Indicatore", "Settore", "Actual", "Consensus",
                    "Surprise", "Z-Score", "Data"
                ])
                df["Z-Score"] = df["Z-Score"].round(2)
                df["Surprise"] = df["Surprise"].round(3)
                df["Actual"] = df["Actual"].round(3)
                df["Consensus"] = df["Consensus"].round(3)
                st.dataframe(df, use_container_width=True, hide_index=True)
        except Exception as exc:
            st.warning(f"Ranking non disponibile: {exc}")

    # ── Tab 3: Sector Trend ───────────────────────────────────────────────────
    with tab_sector:
        st.subheader("Trend EMA per Settore — Ultime 26 Settimane")
        try:
            import pandas as pd
            rows = db.query(
                "SELECT score_date, sector, score_ema, score_momentum "
                "FROM surprise_sector_score "
                "WHERE score_date >= CURRENT_DATE - INTERVAL 180 DAY "
                "ORDER BY score_date"
            )
            if not rows:
                st.info("Nessun dato trend settoriale disponibile.")
            else:
                df = pd.DataFrame(rows, columns=["Data", "Settore", "EMA", "Momentum"])
                df["Data"] = pd.to_datetime(df["Data"])

                for sector in _SECTOR_ORDER:
                    sub = df[df["Settore"] == sector]
                    if sub.empty:
                        continue
                    icon = _SECTOR_ICONS.get(sector, "")
                    st.subheader(f"{icon} {sector.capitalize()}")
                    sub_plot = sub.set_index("Data")[["EMA", "Momentum"]]
                    st.line_chart(sub_plot, height=180)
                    latest = sub.iloc[-1]
                    direction = "▲ improving" if latest.get("Momentum", 0) > 0.15 else (
                        "▼ deteriorating" if latest.get("Momentum", 0) < -0.15 else "→ stable"
                    )
                    st.caption(f"EMA: {latest['EMA']:+.3f}  ·  Momentum: {direction}")
                    st.divider()

        except Exception as exc:
            st.warning(f"Trend settoriale non disponibile: {exc}")
