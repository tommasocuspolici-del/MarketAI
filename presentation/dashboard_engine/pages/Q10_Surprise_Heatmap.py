# ruff: noqa: N999
"""Q10 — Surprise Heatmap (Blocco D): heatmap interattiva 25 indicatori × 12 mesi."""
from __future__ import annotations
from typing import TYPE_CHECKING
from presentation.ui.page_factory import render_page
from presentation.ui.layout import render_section_header

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "1.0.0"


def body_surprise_heatmap(tokens: DesignTokens) -> None:
    try:
        import streamlit as st
    except ImportError:
        return

    import pandas as pd
    import numpy as np
    import plotly.graph_objects as go
    import io
    from shared.db.duckdb_client import DuckDBClient
    from shared.constants import DUCKDB_PATH

    render_section_header("🗺️ Surprise Heatmap — Dettaglio Indicatori",
        "25 indicatori × 12 mesi · Click su cella per dettaglio · Export CSV")

    # Filtri
    all_sectors = ["labour", "growth", "inflation", "housing", "trade_external"]
    sectors_sel = st.multiselect(
        "Filtra settori", options=all_sectors, default=all_sectors, key="q10_sectors"
    )

    try:
        db = DuckDBClient(path=DUCKDB_PATH)
        sectors_placeholder = ",".join(f"'{s}'" for s in sectors_sel)
        rows = db.query(
            f"SELECT release_date, indicator_code, sector, consensus_value, "
            f"actual_value, surprise_raw, surprise_z FROM economic_consensus "
            f"WHERE sector IN ({sectors_placeholder}) "
            f"AND release_date >= CURRENT_DATE - INTERVAL 12 MONTH "
            f"ORDER BY release_date DESC LIMIT 500"
        )
    except Exception:
        rows = None

    if not rows:
        st.info("⏳ Nessun dato consensus disponibile.")
        st.caption(
            "Per popolare la heatmap: carica i dati consensus tramite il "
            "ConsensusLoader o inserisci manualmente in `config/consensus_manual.yaml`."
        )
        return

    df = pd.DataFrame(rows, columns=[
        "release_date","indicator_code","sector","consensus","actual","surprise_raw","surprise_z"
    ])
    df["release_date"] = pd.to_datetime(df["release_date"])
    df["month"] = df["release_date"].dt.to_period("M").astype(str)

    # Pivot: indicatori (righe) × mesi (colonne)
    pivot = df.pivot_table(
        index="indicator_code", columns="month", values="surprise_z", aggfunc="mean"
    )

    c = tokens.colors
    fig = go.Figure(go.Heatmap(
        z=pivot.values,
        x=list(pivot.columns),
        y=list(pivot.index),
        colorscale=[[0, "#dc2626"], [0.5, "#1e293b"], [1, "#16a34a"]],
        zmid=0, zmin=-3, zmax=3,
        text=[[f"{v:.2f}" if not np.isnan(v) else "N/D" for v in row]
              for row in pivot.values],
        texttemplate="%{text}",
        colorbar={"title": "Z-Score"},
        hovertemplate=(
            "Indicatore: %{y}<br>Mese: %{x}<br>Z-Score: %{z:.3f}"
            "<br>Verde = beat consensus · Rosso = miss<extra></extra>"
        ),
    ))
    fig.update_layout(
        title="Heatmap Sorprese Economiche (Z-Score) — Ultimi 12 Mesi",
        paper_bgcolor=c.bg_primary, font={"color": c.text_primary},
        height=max(350, len(pivot) * 25 + 100),
        margin={"t": 50, "b": 60},
    )
    st.plotly_chart(fig, use_container_width=True)

    # Export CSV
    csv_buf = io.StringIO()
    df.to_csv(csv_buf, index=False)
    st.download_button(
        "📥 Esporta CSV",
        data=csv_buf.getvalue(),
        file_name="surprise_heatmap.csv",
        mime="text/csv",
    )

    # Comparazione con S&P500 YoY (placeholder)
    st.divider()
    st.markdown("### 📈 Overlay S&P 500 YoY")
    st.info(
        "ℹ️ Il confronto con i rendimenti S&P 500 YoY verrà aggiunto quando "
        "la serie storica sarà sincronizzata nel DB (dati da LiveMarketService)."
    )


if __name__ == "__main__":  # pragma: no cover
    render_page("Surprise Heatmap", "🗺️", body_surprise_heatmap)
