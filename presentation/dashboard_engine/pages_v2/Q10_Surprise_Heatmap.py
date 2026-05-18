# ruff: noqa: N999
"""Q10 — Economic Surprise Heatmap (v8.4 — fix tabelle + pipeline).

Corregge:
  - Tabelle inesistenti (economic_surprise → economic_consensus, z_score → surprise_z;
    surprise_sector_score → sector_surprise_index, score_date → snapshot_date, ecc.)
  - Mancanza bottone "Carica consensus" → aggiunto, riusa pipeline di M5.
"""
from __future__ import annotations

__version__ = "8.4.0"
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

    st.title("Economic Surprise — Heatmap")
    cols_top = st.columns([3, 1, 1])
    with cols_top[1]:
        if st.button("Carica consensus", key="q10v2_load_consensus",
                     help="Esegue la pipeline: YAML → macro_series → z-score → segnale"):
            with st.spinner("Pipeline in esecuzione…"):
                try:
                    from shared.db.duckdb_client import get_duckdb_client
                    from presentation.dashboard_engine.pages_v2.M5_Economic_Surprise import (
                        _run_surprise_pipeline,
                    )
                    db_pipe = get_duckdb_client()
                    r = _run_surprise_pipeline(db_pipe, st)
                    parts = [f"Consensus YAML: {r['yaml_rows']} righe"]
                    if r["macro_rows"] > 0:
                        parts.append(f"Actuals da FRED: {r['macro_rows']} righe")
                    else:
                        parts.append("Actuals: 0 — carica prima FRED da M3 Labour Market")
                    if r["calc_rows"] > 0:
                        parts.append(f"Z-score: {r['calc_rows']} righe")
                    if r["sector_count"] > 0:
                        parts.append(f"Settori: {r['sector_count']}")
                    if r["signal_value"] is not None:
                        parts.append(f"Segnale: {r['signal_value']:+.3f}")
                    st.success(" · ".join(parts))
                    if r["macro_rows"] == 0:
                        st.info("Per popolare i dati reali vai su M3 Labour Market → Carica da FRED.")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as exc:
                    st.error(f"Errore pipeline: {type(exc).__name__}: {exc}")
    with cols_top[2]:
        if st.button("Aggiorna", key="q10v2_refresh"):
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
        "Heatmap 12M",
        "Z-Score Ranking",
        "Sector Trend",
    ])

    # ── Tab 1: Heatmap ────────────────────────────────────────────────────────
    with tab_heatmap:
        st.subheader("Z-Score Sorprese — Ultimi 12 Mesi")
        try:
            import pandas as pd
            rows = db.query(
                "SELECT indicator_code, sector, surprise_z, release_date "
                "FROM economic_consensus "
                "WHERE release_date >= CURRENT_DATE - INTERVAL 365 DAY "
                "AND surprise_z IS NOT NULL "
                "ORDER BY release_date"
            )
            if not rows:
                st.info(
                    "Nessun dato disponibile. Premi 'Carica consensus' per eseguire la pipeline."
                )
            else:
                df = pd.DataFrame(rows, columns=["Indicatore", "Settore", "Z-Score", "Data"])
                df["Mese"] = pd.to_datetime(df["Data"]).dt.to_period("M").astype(str)

                pivot = df.pivot_table(
                    index="Indicatore", columns="Mese",
                    values="Z-Score", aggfunc="last"
                ).round(2)

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
                    "Z > +2 sorpresa molto positiva · "
                    "Z < -2 sorpresa molto negativa"
                )
        except Exception as exc:
            st.warning(f"Heatmap non disponibile: {exc}")

    # ── Tab 2: Z-Score Ranking ────────────────────────────────────────────────
    with tab_ranking:
        st.subheader("Ranking Z-Score — Ultimi 90 Giorni")

        sector_filter = st.selectbox(
            "Filtra per settore",
            ["tutti"] + _SECTOR_ORDER,
            format_func=lambda s: f"{_SECTOR_ICONS.get(s, '')} {s.capitalize()}" if s != "tutti" else "Tutti",
        )

        try:
            import pandas as pd
            _VALID = {"labour", "growth", "inflation", "housing", "trade_external"}
            safe_sector = sector_filter if sector_filter in _VALID else None

            base_query = (
                "SELECT indicator_code, sector, actual_value, consensus_value, "
                "surprise_raw, surprise_z, release_date "
                "FROM economic_consensus "
                "WHERE release_date >= CURRENT_DATE - INTERVAL 90 DAY "
                "AND surprise_z IS NOT NULL"
            )
            if safe_sector:
                rows = db.query(
                    base_query + " AND sector=? ORDER BY ABS(surprise_z) DESC NULLS LAST LIMIT 25",
                    [safe_sector],
                )
            else:
                rows = db.query(
                    base_query + " ORDER BY ABS(surprise_z) DESC NULLS LAST LIMIT 25"
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
        st.subheader("Trend per Settore — Ultime 26 Settimane")
        try:
            import pandas as pd
            rows = db.query(
                "SELECT snapshot_date, sector, surprise_index, momentum_1m "
                "FROM sector_surprise_index "
                "WHERE snapshot_date >= CURRENT_DATE - INTERVAL 180 DAY "
                "ORDER BY snapshot_date"
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
                    mom = latest.get("Momentum", 0) or 0
                    direction = "▲ improving" if mom > 0.15 else (
                        "▼ deteriorating" if mom < -0.15 else "→ stable"
                    )
                    st.caption(f"Surprise Index: {latest['EMA']:+.3f}  ·  Momentum: {direction}")
                    st.divider()

        except Exception as exc:
            st.warning(f"Trend settoriale non disponibile: {exc}")
