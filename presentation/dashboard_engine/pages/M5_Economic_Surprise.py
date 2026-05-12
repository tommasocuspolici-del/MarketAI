# ruff: noqa: N999
"""M5 — Economic Surprise Engine (Blocco D).

Heatmap settoriale + dettaglio indicatore + momentum trend.
Carica gracefully con DB vuoto.
"""
from __future__ import annotations
from typing import TYPE_CHECKING
from presentation.ui.page_factory import render_page
from presentation.ui.layout import render_section_header

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "1.0.0"


def _load_sector_data(db):
    try:
        rows = db.query(
            "SELECT sector, snapshot_date, surprise_index, regime, beat_count, miss_count, data_points "
            "FROM sector_surprise_index ORDER BY snapshot_date DESC LIMIT 200"
        )
        return rows
    except Exception:
        return None


# Settori validi — whitelist per prevenire SQL injection (BUG FIX: f-string su input utente)
_VALID_SECTORS = frozenset({"labour", "growth", "inflation", "housing", "trade_external"})


def _load_indicator_data(db, sector: str):
    """Carica dati indicatori per settore.

    SECURITY FIX: validazione whitelist prima di usare il valore in query.
    Mai usare f-string con input utente direttamente in SQL.
    """
    if sector not in _VALID_SECTORS:
        return None
    try:
        # Query parametrizzata — nessuna f-string con user input
        rows = db.query(
            "SELECT release_date, indicator_code, consensus_value, actual_value, "
            "surprise_raw, surprise_z FROM economic_consensus "
            "WHERE sector = ? ORDER BY release_date DESC LIMIT 60",
            [sector],
        )
        return rows
    except Exception:
        return None


def body_economic_surprise(tokens: DesignTokens) -> None:
    """Body Streamlit pagina M5."""
    try:
        import streamlit as st
    except ImportError:
        return

    import pandas as pd
    import plotly.graph_objects as go
    import numpy as np
    from shared.db.duckdb_client import DuckDBClient
    from shared.constants import DUCKDB_PATH

    render_section_header("⚡ Economic Surprise Engine",
        "Misura lo scarto tra previsioni consensus e dati effettivi per settore.")

    try:
        db = DuckDBClient(path=DUCKDB_PATH)
    except Exception:
        st.error("❌ Impossibile connettersi al database.")
        return

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
        st.info("⏳ Nessun segnale surprise calcolato. Carica i dati consensus prima.")

    st.divider()

    # ── Panel 1: Heatmap settoriale ────────────────────────────────────
    st.markdown("### 🗺️ Heatmap Sorprese Settoriali")
    rows = _load_sector_data(db)

    if not rows:
        st.info("⏳ Nessun dato settoriale disponibile.")
    else:
        df_sec = pd.DataFrame(
            rows, columns=["sector","snapshot_date","surprise_index","regime","beat_count","miss_count","data_points"]
        )
        df_sec["snapshot_date"] = pd.to_datetime(df_sec["snapshot_date"])

        # Pivot: settori × mesi
        df_sec["month"] = df_sec["snapshot_date"].dt.to_period("M").astype(str)
        pivot = df_sec.pivot_table(
            index="sector", columns="month", values="surprise_index", aggfunc="mean"
        ).iloc[:, -6:]  # ultimi 6 mesi

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
