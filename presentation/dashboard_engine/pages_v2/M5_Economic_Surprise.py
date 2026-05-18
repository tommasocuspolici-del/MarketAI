# ruff: noqa: N999
"""M5 — Economic Surprise Index (v8.4 — fix tabelle + pipeline).

Corregge:
  - Tabelle inesistenti (economic_surprise, surprise_sector_score, economic_surprise_index)
    → tabelle reali (economic_consensus, sector_surprise_index, surprise_signal).
  - Mancanza bottone "📥 Carica consensus" → aggiunto, esegue pipeline completa.
"""
from __future__ import annotations

__version__ = "8.4.0"
__all__ = ["body_m5_economic_surprise"]

# ─── Mapping FRED series → trasformazione per calcolo actuals da macro_series ──
_FRED_TRANSFORMS: dict[str, str] = {
    "PAYEMS":        "diff",      # NFP: variazione mensile in migliaia
    "ICSA":          "level",     # Initial Claims: livello settimanale
    "UNRATE":        "level",     # Unemployment Rate: % livello
    "CES0500000003": "pct_mom",   # AHE: variazione % mensile
    "RSAFS":         "pct_mom",   # Retail Sales: variazione % mensile
    "CPIAUCSL":      "pct_yoy",   # CPI: variazione % annua
    "PCEPI":         "pct_yoy",   # PCE: variazione % annua
    "HOUST":         "level",     # Housing Starts: migliaia
    "BOPGSTB":       "level",     # Trade Balance: miliardi USD
}


def _apply_transform(values, transform: str):
    import numpy as np
    import pandas as pd
    s = pd.Series(values, dtype=float)
    if transform == "diff":
        return s.diff()
    if transform == "pct_mom":
        return s.pct_change() * 100
    if transform == "pct_yoy":
        return s.pct_change(periods=12) * 100
    return s  # level


def _populate_actuals_from_macro_series(db) -> int:
    """Legge macro_series DuckDB e popola economic_consensus con actuals storici."""
    import yaml
    from pathlib import Path
    import pandas as pd

    yaml_path = Path(__file__).resolve().parents[3] / "config" / "surprise_engine.yaml"
    try:
        with yaml_path.open() as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        return 0

    indicator_map: dict[str, dict] = {}
    for sector, sector_cfg in cfg.get("sectors", {}).items():
        for ind in sector_cfg.get("indicators", []):
            code = str(ind.get("code", "")).upper()
            fred_id = ind.get("fred_actual", "")
            if code and fred_id:
                indicator_map[code] = {
                    "fred_actual": fred_id,
                    "sector": sector,
                    "weight": float(ind.get("weight", 1.0)),
                }

    if not indicator_map:
        return 0

    inserted = 0
    try:
        with db.transaction() as conn:
            for ind_code, meta in indicator_map.items():
                fred_id = meta["fred_actual"]
                sector = meta["sector"]
                transform = _FRED_TRANSFORMS.get(fred_id, "level")

                try:
                    rows = conn.execute(
                        "SELECT ts, value FROM macro_series "
                        "WHERE series_id = ? AND value IS NOT NULL "
                        "ORDER BY ts",
                        [fred_id],
                    ).fetchall()
                except Exception:
                    continue

                if len(rows) < 2:
                    continue

                dates = [r[0] for r in rows]
                values = [float(r[1]) for r in rows]
                transformed = _apply_transform(values, transform)

                for i, (ts, actual_val) in enumerate(zip(dates, transformed)):
                    if i == 0 or pd.isna(actual_val):
                        continue
                    prior_val = float(transformed.iloc[i - 1]) if not pd.isna(transformed.iloc[i - 1]) else None
                    if prior_val is None:
                        continue

                    release_date = pd.Timestamp(ts).date()
                    try:
                        conn.execute(
                            """INSERT OR REPLACE INTO economic_consensus
                               (release_date, indicator_code, sector,
                                consensus_value, actual_value, prior_value, source)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            [release_date, ind_code, sector,
                             float(prior_val), float(actual_val), float(prior_val),
                             "macro_series_derived"],
                        )
                        inserted += 1
                    except Exception:
                        continue
    except Exception:
        pass

    return inserted


def _load_indicator_weights_from_yaml() -> dict[str, dict[str, float]]:
    from pathlib import Path
    import yaml

    yaml_path = Path(__file__).resolve().parents[3] / "config" / "surprise_engine.yaml"
    try:
        with yaml_path.open() as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        return {}

    weights: dict[str, dict[str, float]] = {}
    for sector, sector_cfg in cfg.get("sectors", {}).items():
        weights[sector] = {}
        for ind in sector_cfg.get("indicators", []):
            code = str(ind.get("code", "")).upper()
            if code:
                weights[sector][code] = float(ind.get("weight", 1.0))
    return weights


def _run_surprise_pipeline(db, st_module) -> dict:
    """Esegue la pipeline completa economic surprise.

    Ritorna dict con campi: yaml_rows, macro_rows, calc_rows, sector_count, signal_value.
    """
    st = st_module
    result = {"yaml_rows": 0, "macro_rows": 0, "calc_rows": 0, "sector_count": 0, "signal_value": None}

    try:
        from shared.db.duckdb_migrator import run_pending_migrations
        run_pending_migrations()
    except Exception as exc:
        st.warning(f"Migrations parziali: {exc}")

    try:
        from engine.analytics.surprise_engine.consensus_loader import ConsensusLoader
        loader = ConsensusLoader(client=db)
        batch = loader.load_yaml()
        loader.save(batch)
        result["yaml_rows"] = batch.row_count
    except Exception as exc:
        st.error(f"Errore ConsensusLoader: {type(exc).__name__}: {exc}")
        return result

    macro_rows = _populate_actuals_from_macro_series(db)
    result["macro_rows"] = macro_rows

    try:
        df_calc = loader.build_for_calculator()
        result["calc_rows"] = len(df_calc)
    except Exception as exc:
        st.error(f"Errore build_for_calculator: {exc}")
        return result

    if df_calc.empty:
        return result

    try:
        from engine.analytics.surprise_engine.surprise_engine import (
            SurpriseCalculator,
            SectorSurpriseAggregator,
            SurpriseSignalGenerator,
        )

        raw_conn = db.connection
        calc = SurpriseCalculator(duckdb=raw_conn)
        df_computed = calc.compute_from_df(df_calc)
        calc.persist_to_db(df_computed)
    except Exception as exc:
        st.error(f"Errore SurpriseCalculator: {exc}")
        return result

    try:
        indicator_weights = _load_indicator_weights_from_yaml()
        agg = SectorSurpriseAggregator(indicator_weights=indicator_weights, duckdb=raw_conn)
        sector_indices = agg.aggregate(df_computed)
        result["sector_count"] = len(sector_indices)
    except Exception as exc:
        st.error(f"Errore SectorSurpriseAggregator: {exc}")
        return result

    try:
        sig_gen = SurpriseSignalGenerator(duckdb=raw_conn)
        signal = sig_gen.generate(sector_indices)
        result["signal_value"] = signal.signal_value
    except Exception as exc:
        st.warning(f"Errore SurpriseSignalGenerator: {exc}")

    return result


def body_m5_economic_surprise(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    st.title("Economic Surprise Index")
    cols_top = st.columns([3, 1, 1])
    with cols_top[1]:
        if st.button("Carica consensus", key="m5v2_load_consensus",
                     help="Esegue la pipeline: YAML → macro_series → z-score → segnale"):
            with st.spinner("Pipeline in esecuzione…"):
                try:
                    from shared.db.duckdb_client import get_duckdb_client
                    db_pipe = get_duckdb_client()
                    r = _run_surprise_pipeline(db_pipe, st)
                    parts = [f"Consensus YAML: {r['yaml_rows']} righe"]
                    if r["macro_rows"] > 0:
                        parts.append(f"Actuals da FRED: {r['macro_rows']} righe")
                    else:
                        parts.append("Actuals: 0 — carica prima FRED da M3 Labour Market")
                    if r["calc_rows"] > 0:
                        parts.append(f"Z-score calcolati: {r['calc_rows']} righe")
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
        if st.button("Aggiorna", key="m5v2_refresh"):
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
        "ESI Composite",
        "Indicatori",
        "Momentum",
        "Segnale",
    ])

    # ── Tab 1: ESI Composite ─────────────────────────────────────────────────
    with tab_esi:
        st.subheader("Economic Surprise Index — Score Composito")
        try:
            rows = db.query(
                "SELECT generated_at::DATE AS index_date, signal_value "
                "FROM surprise_signal ORDER BY generated_at DESC LIMIT 1"
            )
            if not rows:
                st.info("Nessun dato ESI. Premi 'Carica consensus' per eseguire la pipeline.")
            else:
                r = rows[0]
                esi = r[1]
                color = "verde" if esi and esi > 0.1 else ("rosso" if esi and esi < -0.1 else "neutro")
                emoji = "" if esi and esi > 0.1 else ("" if esi and esi < -0.1 else "")
                st.metric(
                    f"ESI Composite ({color})",
                    f"{esi:+.3f}" if esi is not None else "N/A",
                    help="[-1,+1]: +1 = economia sorprende positivamente su tutti i fronti",
                )
                st.caption(f"Data: {r[0]}")
        except Exception as exc:
            st.warning(f"ESI non disponibile: {exc}")

        st.divider()
        st.subheader("Score per Settore")
        sectors = ["labour", "growth", "inflation", "housing"]
        sector_icons = {"labour": "👷", "growth": "📈", "inflation": "🔥", "housing": "🏠"}
        try:
            cols = st.columns(4)
            for col, sector in zip(cols, sectors):
                rows_s = db.query(
                    "SELECT surprise_index, regime FROM sector_surprise_index "
                    "WHERE sector=? ORDER BY snapshot_date DESC LIMIT 1",
                    [sector],
                )
                with col:
                    if rows_s:
                        score = rows_s[0][0]
                        regime = rows_s[0][1] or "neutral"
                        arrow = "▲" if regime == "positive_surprise" else ("▼" if regime == "negative_surprise" else "→")
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
                "surprise_raw, surprise_z, release_date "
                "FROM economic_consensus "
                "WHERE release_date >= CURRENT_DATE - INTERVAL 90 DAY "
                "AND surprise_z IS NOT NULL "
                "ORDER BY ABS(surprise_z) DESC NULLS LAST LIMIT 30"
            )
            if not rows:
                st.info("Nessun dato disponibile. Esegui la pipeline con 'Carica consensus'.")
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
        st.subheader("Momentum ESI — Score Ultimi 90 Giorni")
        try:
            import pandas as pd
            rows = db.query(
                "SELECT snapshot_date, sector, surprise_index, momentum_1m "
                "FROM sector_surprise_index "
                "WHERE snapshot_date >= CURRENT_DATE - INTERVAL 90 DAY "
                "ORDER BY snapshot_date, sector"
            )
            if not rows:
                st.info("Nessun dato momentum disponibile.")
            else:
                df = pd.DataFrame(rows, columns=["Data", "Settore", "EMA", "Momentum"])
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
                "SELECT generated_at::DATE AS index_date, signal_value "
                "FROM surprise_signal "
                "ORDER BY generated_at DESC LIMIT 52"
            )
            if not rows:
                st.info("Nessun dato segnale disponibile.")
            else:
                df = pd.DataFrame(rows, columns=["Data", "Segnale"])
                df = df.sort_values("Data")
                st.line_chart(df.set_index("Data")["Segnale"], height=300)
                st.caption(
                    "**Segnale** = ESI normalizzato [-1,+1] per Composite Signal v2. "
                    "+1 = economia sorprende positivamente · -1 = sorprese negative diffuse."
                )
        except Exception as exc:
            st.warning(f"Segnale non disponibile: {exc}")
