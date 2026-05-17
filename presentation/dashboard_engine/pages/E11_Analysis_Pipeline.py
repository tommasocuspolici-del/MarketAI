# ruff: noqa: N999
"""E11 — Analysis Pipeline (stepper + manual refresh + log)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from presentation.ui.components.pipeline_stepper import (
    PipelineStep,
    render_pipeline_stepper,
)
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "6.0.0"

__all__ = ["body_analysis_pipeline"]


def body_analysis_pipeline(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit-rendered body
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st
    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="e11_refresh"):
            st.cache_data.clear()
            st.rerun()
    render_section_header("📊 Stato Database — Tabelle chiave")

    # Tabelle DuckDB da monitorare
    _TABLES = [
        ("prices",               "Prezzi OHLCV"),
        ("claims_cycle",         "Labour: Claims settimanali"),
        ("jolts_monthly",        "Labour: JOLTS mensili"),
        ("payroll_sector",       "Labour: Payroll per settore"),
        ("economic_consensus",   "Economic Surprise: consensus"),
        ("sector_surprise_index","Economic Surprise: indice settori"),
        ("labour_forecasts",     "Labour: Previsioni ARIMA+Ridge"),
        ("instrument_registry",  "Instrument Registry eToro"),
    ]

    rows_data = []
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
        for table, label in _TABLES:
            try:
                res = db.query(f"SELECT COUNT(*) FROM {table}")
                count = res[0][0] if res else 0
                status = "success" if count > 0 else "pending"
                rows_data.append({"Tabella": table, "Descrizione": label,
                                  "Righe": count, "Stato": "✅" if count > 0 else "⏳"})
            except Exception:
                rows_data.append({"Tabella": table, "Descrizione": label,
                                  "Righe": "N/A", "Stato": "❌"})
    except Exception:
        st.error("❌ DuckDB non raggiungibile.")
        rows_data = []

    if rows_data:
        import pandas as pd
        df_status = pd.DataFrame(rows_data)
        steps = [
            PipelineStep(
                name=r["Tabella"],
                status="success" if r["Stato"] == "✅" else ("pending" if r["Stato"] == "⏳" else "error"),
                duration_ms=None,
            )
            for r in rows_data
        ]
        render_pipeline_stepper(tokens, steps)
        st.dataframe(df_status, use_container_width=True, hide_index=True)

    st.divider()
    render_section_header("⚡ FRED API")
    try:
        from engine.market_data.fred_simple_client import FredSimpleClient
        fred = FredSimpleClient()
        if fred.has_api_key:
            st.success("✅ FRED_API_KEY configurata")
        else:
            st.warning("⚠️ FRED_API_KEY assente — caricamento dati FRED non disponibile")
    except Exception:
        st.error("❌ FredSimpleClient non caricabile")


if __name__ == "__main__":   # pragma: no cover
    render_page("Analysis Pipeline", "⚙️", body_analysis_pipeline)
