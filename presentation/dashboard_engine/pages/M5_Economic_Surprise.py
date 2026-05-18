# ruff: noqa: N999
"""M5 — Economic Surprise Engine (Blocco D).

Heatmap settoriale + dettaglio indicatore + momentum trend.
Carica gracefully con DB vuoto.

Pipeline completa:
  1. ConsensusLoader.load_yaml() → consensus_estimates
  2. _populate_actuals_from_macro_series() → economic_consensus (actuals da macro_series)
  3. ConsensusLoader.build_for_calculator() → DataFrame con consensus + actuals
  4. SurpriseCalculator.compute_from_df() → z-scores
  5. SurpriseCalculator.persist_to_db() → economic_consensus aggiornato
  6. SectorSurpriseAggregator.aggregate() → sector_surprise_index
  7. SurpriseSignalGenerator.generate() → surprise_signal
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from presentation.ui.page_factory import render_page
from presentation.ui.layout import render_section_header

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "2.0.0"

# Mapping FRED series → transformation type (per calcolo unità corrette)
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


def _load_sector_data(db):
    try:
        rows = db.query(
            "SELECT sector, snapshot_date, surprise_index, regime, beat_count, miss_count, data_points "
            "FROM sector_surprise_index ORDER BY snapshot_date DESC LIMIT 200"
        )
        return rows
    except Exception:
        return None


# Settori validi — whitelist per prevenire SQL injection
_VALID_SECTORS = frozenset({"labour", "growth", "inflation", "housing", "trade_external"})


def _load_indicator_data(db, sector: str):
    if sector not in _VALID_SECTORS:
        return None
    try:
        rows = db.query(
            "SELECT release_date, indicator_code, consensus_value, actual_value, "
            "surprise_raw, surprise_z FROM economic_consensus "
            "WHERE sector = ? ORDER BY release_date DESC LIMIT 60",
            [sector],
        )
        return rows
    except Exception:
        return None


def _apply_transform(values, transform: str):
    """Applica la trasformazione corretta a una serie temporale."""
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
    """Legge macro_series DuckDB e popola economic_consensus con actuals storici.

    Usa il valore del periodo precedente come consensus naive (CESI-style).
    Restituisce il numero di righe inserite.
    """
    import yaml
    from pathlib import Path
    import pandas as pd

    # Carica mappa indicator_code → {fred_actual, sector}
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

                import numpy as np
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
    """Carica pesi indicatori da surprise_engine.yaml per SectorSurpriseAggregator."""
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

    Returns dict con campi: yaml_rows, macro_rows, calc_rows, sector_count, signal_value.
    """
    st = st_module
    result = {"yaml_rows": 0, "macro_rows": 0, "calc_rows": 0, "sector_count": 0, "signal_value": None}

    # ── Step 1: assicura che le tabelle DuckDB esistano ───────────────────
    try:
        from shared.db.duckdb_migrator import run_pending_migrations
        run_pending_migrations()
    except Exception as exc:
        st.warning(f"⚠️ DuckDB migrations parziali: {exc}")

    # ── Step 2: carica consensus YAML → consensus_estimates ───────────────
    try:
        from engine.analytics.surprise_engine.consensus_loader import ConsensusLoader
        loader = ConsensusLoader(client=db)
        batch = loader.load_yaml()
        loader.save(batch)
        result["yaml_rows"] = batch.row_count
    except Exception as exc:
        st.error(f"❌ Errore ConsensusLoader: {type(exc).__name__}: {exc}")
        return result

    # ── Step 3: popola actuals da macro_series → economic_consensus ───────
    macro_rows = _populate_actuals_from_macro_series(db)
    result["macro_rows"] = macro_rows

    # ── Step 4: build DataFrame per SurpriseCalculator ────────────────────
    try:
        df_calc = loader.build_for_calculator()
        result["calc_rows"] = len(df_calc)
    except Exception as exc:
        st.error(f"❌ Errore build_for_calculator: {exc}")
        return result

    if df_calc.empty:
        return result

    # ── Step 5: calcola z-score e persisti in economic_consensus ─────────
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
        st.error(f"❌ Errore SurpriseCalculator: {exc}")
        return result

    # ── Step 6: aggrega settori → sector_surprise_index ──────────────────
    try:
        indicator_weights = _load_indicator_weights_from_yaml()
        agg = SectorSurpriseAggregator(
            indicator_weights=indicator_weights,
            duckdb=raw_conn,
        )
        sector_indices = agg.aggregate(df_computed)
        result["sector_count"] = len(sector_indices)
    except Exception as exc:
        st.error(f"❌ Errore SectorSurpriseAggregator: {exc}")
        return result

    # ── Step 7: genera segnale composito → surprise_signal ───────────────
    try:
        sig_gen = SurpriseSignalGenerator(duckdb=raw_conn)
        signal = sig_gen.generate(sector_indices)
        result["signal_value"] = signal.signal_value
    except Exception as exc:
        st.warning(f"⚠️ Errore SurpriseSignalGenerator: {exc}")

    return result


def body_economic_surprise(tokens: DesignTokens) -> None:
    """Body Streamlit pagina M5."""
    import streamlit as st

    import pandas as pd
    import plotly.graph_objects as go
    import numpy as np
    from shared.db.duckdb_client import get_duckdb_client

    render_section_header("⚡ Economic Surprise Engine",
        "Misura lo scarto tra previsioni consensus e dati effettivi per settore.")

    try:
        db = get_duckdb_client()
    except Exception:
        st.error("❌ Impossibile connettersi al database.")
        return

    # ── Controlli ─────────────────────────────────────────────────────────
    cols_top = st.columns([3, 1, 1])
    with cols_top[1]:
        if st.button("📥 Carica consensus", key="m5_load_consensus",
                     help="Carica consensus YAML, popola actuals da macro_series e calcola sorprese"):
            with st.spinner("Pipeline surprise in esecuzione…"):
                try:
                    r = _run_surprise_pipeline(db, st)
                    parts = [f"Consensus YAML: {r['yaml_rows']} righe"]
                    if r["macro_rows"] > 0:
                        parts.append(f"Actuals da macro_series: {r['macro_rows']} righe")
                    else:
                        parts.append("Actuals da macro_series: 0 (nessun dato FRED in DB)")
                    if r["calc_rows"] > 0:
                        parts.append(f"Z-score calcolati: {r['calc_rows']} righe")
                    if r["sector_count"] > 0:
                        parts.append(f"Settori aggregati: {r['sector_count']}")
                    if r["signal_value"] is not None:
                        parts.append(f"Segnale composito: {r['signal_value']:+.3f}")
                    st.success("✅ " + " · ".join(parts))
                    if r["macro_rows"] == 0:
                        st.info(
                            "ℹ️ Nessun dato storico trovato in macro_series. "
                            "Per popolare i dati reali, vai su **M3 Labour Market** → "
                            "📥 Carica da FRED, oppure esegui il job scheduler macro."
                        )
                    st.cache_data.clear()
                    st.rerun()
                except Exception as exc:
                    st.error(f"❌ Errore pipeline: {type(exc).__name__}: {exc}")

    with cols_top[2]:
        if st.button("🔄 Aggiorna", key="m5_refresh"):
            st.cache_data.clear()
            st.rerun()

    # ── Header: segnale composito ──────────────────────────────────────
    try:
        sig_rows = db.query(
            "SELECT signal_value, dominant_sector, beat_count, miss_count "
            "FROM surprise_signal ORDER BY generated_at DESC LIMIT 1"
        )
    except Exception:
        sig_rows = None

    if sig_rows:
        sv, dom, beat, miss = sig_rows[0]
        c1, c2, c3 = st.columns(3)
        with c1:
            color = "🟢" if float(sv) > 0.1 else ("🔴" if float(sv) < -0.1 else "🟡")
            st.metric("Surprise Score", f"{color} {float(sv):+.3f}")
        with c2:
            st.metric("Settore dominante", str(dom))
        with c3:
            st.metric("Beat / Miss", f"{beat} / {miss}")
    else:
        st.info("⏳ Nessun segnale surprise calcolato. Clicca **📥 Carica consensus** per eseguire la pipeline.")

    st.divider()

    # ── Panel 1: Heatmap settoriale ────────────────────────────────────
    st.markdown("### 🗺️ Heatmap Sorprese Settoriali")
    rows = _load_sector_data(db)

    if not rows:
        st.info("⏳ Nessun dato settoriale. Clicca **📥 Carica consensus** per avviare la pipeline.")
    else:
        df_sec = pd.DataFrame(
            rows, columns=["sector","snapshot_date","surprise_index","regime","beat_count","miss_count","data_points"]
        )
        df_sec["snapshot_date"] = pd.to_datetime(df_sec["snapshot_date"])

        df_sec["month"] = df_sec["snapshot_date"].dt.to_period("M").astype(str)
        pivot = df_sec.pivot_table(
            index="sector", columns="month", values="surprise_index", aggfunc="mean"
        ).iloc[:, -6:]

        if not pivot.empty:
            c = tokens.colors
            fig = go.Figure(go.Heatmap(
                z=pivot.values,
                x=list(pivot.columns),
                y=list(pivot.index),
                colorscale=[[0, "#dc2626"], [0.5, "#1e293b"], [1, "#16a34a"]],
                zmid=0, zmin=-2, zmax=2,
                text=[[f"{v:.2f}" if not np.isnan(v) else "N/D"
                       for v in row] for row in pivot.values],
                texttemplate="%{text}", showscale=True,
                hovertemplate="Settore: %{y}<br>Mese: %{x}<br>Indice: %{z:.3f}<extra></extra>",
            ))
            fig.update_layout(
                title="Indice Sorpresa per Settore (ultimi 6 mesi)",
                paper_bgcolor=c.bg_primary, font={"color": c.text_primary},
                height=300, margin={"t": 40},
            )
            st.plotly_chart(fig, use_container_width=True)

    # ── Panel 2: Dettaglio indicatore ──────────────────────────────────
    st.divider()
    st.markdown("### 🔍 Dettaglio Indicatore")

    sectors_available = list({r[0] for r in (rows or [])}) or ["labour","growth","inflation"]
    sector_sel = st.selectbox("Settore", options=sectors_available, key="m5_sector")

    ind_rows = _load_indicator_data(db, sector_sel)
    if not ind_rows:
        st.info(f"⏳ Nessun indicatore disponibile per il settore '{sector_sel}'.")
    else:
        df_ind = pd.DataFrame(
            ind_rows,
            columns=["release_date","indicator_code","consensus","actual","surprise_raw","surprise_z"]
        )
        df_ind["release_date"] = pd.to_datetime(df_ind["release_date"])

        indicators = df_ind["indicator_code"].unique().tolist()
        ind_sel = st.selectbox("Indicatore", options=indicators, key="m5_indicator")
        df_i = df_ind[df_ind["indicator_code"] == ind_sel].sort_values("release_date").tail(12)

        c = tokens.colors
        col_a, col_b = st.columns(2)
        with col_a:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=df_i["release_date"], y=df_i["actual"],
                                  name="Actual", marker_color=c.accent_primary))
            fig.add_trace(go.Bar(x=df_i["release_date"], y=df_i["consensus"],
                                  name="Consensus", marker_color=c.text_secondary, opacity=0.6))
            fig.update_layout(
                barmode="group", title=f"{ind_sel} — Actual vs Consensus",
                paper_bgcolor=c.bg_primary, font={"color": c.text_primary}, height=280,
            )
            st.plotly_chart(fig, use_container_width=True)
        with col_b:
            fig2 = go.Figure(go.Scatter(
                x=df_i["release_date"], y=df_i["surprise_z"],
                mode="lines+markers", line={"color": c.accent_primary, "width": 2},
                fill="tozeroy",
                fillcolor="rgba(59,130,246,0.15)",
            ))
            fig2.add_hline(y=1, line_dash="dash", line_color=c.positive, opacity=0.5)
            fig2.add_hline(y=-1, line_dash="dash", line_color=c.negative, opacity=0.5)
            fig2.update_layout(
                title="Z-Score Sorprese",
                paper_bgcolor=c.bg_primary, font={"color": c.text_primary}, height=280,
            )
            st.plotly_chart(fig2, use_container_width=True)

        st.dataframe(
            df_i[["release_date","consensus","actual","surprise_raw","surprise_z"]]
            .rename(columns={"release_date":"Data","consensus":"Consensus",
                              "actual":"Actual","surprise_raw":"Sorpresa","surprise_z":"Z-Score"})
            .sort_values("Data", ascending=False),
            use_container_width=True, hide_index=True,
        )


if __name__ == "__main__":  # pragma: no cover
    render_page("Economic Surprise", "⚡", body_economic_surprise)
