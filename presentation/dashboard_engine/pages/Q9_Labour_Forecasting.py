# ruff: noqa: N999
"""Q9 — Labour Forecasting Detail (Blocco D): dettaglio modello previsionale."""
from __future__ import annotations
from typing import TYPE_CHECKING
from presentation.ui.page_factory import render_page
from presentation.ui.layout import render_section_header

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "1.0.0"


def body_labour_forecasting(tokens: DesignTokens) -> None:
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

    import pandas as pd
    from shared.db.duckdb_client import DuckDBClient
    from shared.constants import DUCKDB_PATH

    render_section_header("🔬 Labour Forecasting — Dettaglio Modello",
        "Feature importance Ridge · Ordine ARIMA · Walk-forward accuracy · Scenario sensitivity")

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="q9_refresh"):
            st.cache_data.clear()
            st.rerun()

    try:
        db = DuckDBClient(path=DUCKDB_PATH)
        rows = db.query(
            "SELECT generated_at, horizon, target_metric, forecast_value, forecast_lower, "
            "forecast_upper, model_used, arima_forecast, ridge_forecast "
            "FROM labour_forecasts ORDER BY generated_at DESC LIMIT 50"
        )
    except Exception:
        rows = None

    if not rows:
        st.info("⏳ Nessuna previsione disponibile nel database.")
        st.caption(
            "Esegui il job Labour Market (giovedì 17:00) per generare le previsioni. "
            "Assicurati che FRED_API_KEY sia configurata in `.env`."
        )
        return

    import plotly.graph_objects as go
    df = pd.DataFrame(rows, columns=[
        "generated_at","horizon","target_metric","forecast_value","forecast_lower",
        "forecast_upper","model_used","arima_forecast","ridge_forecast"
    ])

    c = tokens.colors

    # Sezione 3: ARIMA vs Ridge vs Ensemble comparison
    st.markdown("### 📊 Confronto Modelli: ARIMA vs Ridge vs Ensemble")
    for metric in df["target_metric"].unique():
        mdf = df[df["target_metric"] == metric]
        fig = go.Figure()
        for h in ["1M","3M","6M"]:
            row = mdf[mdf["horizon"] == h]
            if row.empty:
                continue
            r = row.iloc[0]
            x = [str(h)]
            fig.add_trace(go.Bar(x=x, y=[r["arima_forecast"]], name="ARIMA",
                                  marker_color=c.accent_primary, legendgroup="arima", showlegend=(h=="1M")))
            fig.add_trace(go.Bar(x=x, y=[r["ridge_forecast"]], name="Ridge",
                                  marker_color=c.positive, legendgroup="ridge", showlegend=(h=="1M")))
            fig.add_trace(go.Bar(x=x, y=[r["forecast_value"]], name="Ensemble",
                                  marker_color="#f59e0b", legendgroup="ensemble", showlegend=(h=="1M")))
        fig.update_layout(
            barmode="group", title=f"{metric} — ARIMA vs Ridge vs Ensemble",
            paper_bgcolor=c.bg_primary, font={"color": c.text_primary}, height=300,
        )
        st.plotly_chart(fig, use_container_width=True)

    # Sezione 4: Walk-forward accuracy placeholder
    st.markdown("### 📈 Walk-Forward Accuracy (ultimi 24 mesi)")
    st.info(
        "ℹ️ Il walk-forward richiede dati storici archiviati nel DB. "
        "Sarà disponibile dopo 3+ mesi di previsioni consecutive."
    )

    # Sezione 5: Scenario sensitivity
    st.markdown("### 🎛️ Scenario Sensitivity")
    st.caption("Sposta lo slider per vedere l'impatto di variazioni nei Claims sul forecast UNRATE.")
    claims_delta = st.slider(
        "Variazione Claims rispetto al baseline (migliaia)",
        min_value=-200, max_value=200, value=0, step=10,
        key="q9_claims_slider",
    )
    if claims_delta != 0:
        # Stima semplificata: ogni +10k claims ≈ +0.02% UNRATE a 3M
        unrate_impact = claims_delta * 0.002
        st.metric(
            "Impatto stimato UNRATE a 3M",
            f"{unrate_impact:+.2f}%",
            help="Stima lineare semplificata. Usare a scopo indicativo.",
        )


if __name__ == "__main__":  # pragma: no cover
    render_page("Labour Forecasting", "🔬", body_labour_forecasting)
