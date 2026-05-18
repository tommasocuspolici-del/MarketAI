# ruff: noqa: N999
"""Q9 — Labour Forecasting Detail (Blocco D): dettaglio modello previsionale."""
from __future__ import annotations
from typing import TYPE_CHECKING
from presentation.ui.page_factory import render_page
from presentation.ui.layout import render_section_header

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "1.0.0"


def _run_forecast_job(st_module) -> None:  # pragma: no cover
    """Genera previsioni UNRATE da FRED e persiste in labour_forecasts."""
    st = st_module
    import pandas as pd
    from datetime import datetime, UTC as _UTC
    from engine.market_data.fred_simple_client import FredSimpleClient, FredKeyMissingError
    from engine.analytics.labour_market.labour_forecast_engine import LabourForecastEngine
    from shared.db.duckdb_client import get_duckdb_client

    fred = FredSimpleClient()
    if not fred.has_api_key:
        st.error("❌ FRED_API_KEY non configurata in .env.")
        return
    try:
        db = get_duckdb_client()
    except Exception as exc:
        st.error(f"❌ DB non disponibile: {exc}")
        return

    # BUGFIX: sort_order="asc" con limit restituisce le osservazioni PIÙ VECCHIE
    # (es. UNRATE dal 1948, ICSA dal 1967) senza sovrapposizione temporale → 0 campioni.
    # Corretto: fetch desc (più recenti prima), poi sort crescente per il modello.
    try:
        unrate_df   = fred.fetch_series("UNRATE",  limit=200, sort_order="desc").sort_values("ts")
        icsa_df     = fred.fetch_series("ICSA",    limit=800, sort_order="desc").sort_values("ts")
        quits_df    = fred.fetch_series("JTSQUR",  limit=200, sort_order="desc").sort_values("ts")
        openings_df = fred.fetch_series("JTSJOR",  limit=200, sort_order="desc").sort_values("ts")
    except FredKeyMissingError:
        st.error("❌ FRED API key non valida o scaduta.")
        return
    except Exception as exc:
        st.error(f"❌ Fetch FRED fallita: {type(exc).__name__}: {str(exc)[:120]}")
        return

    if unrate_df.empty or icsa_df.empty:
        st.error("❌ Serie FRED UNRATE o ICSA vuota — impossibile addestrare.")
        return

    # Allinea su frequenza mensile (UNRATE è mensile, ICSA è settimanale → media mensile)
    unrate = unrate_df.set_index("ts")["value"].astype(float)
    unrate.index = pd.to_datetime(unrate.index).to_period("M").to_timestamp()

    icsa = icsa_df.set_index("ts")["value"].astype(float)
    icsa.index = pd.to_datetime(icsa.index)
    icsa_monthly = icsa.resample("ME").mean()
    icsa_monthly.index = icsa_monthly.index.to_period("M").to_timestamp()

    features = pd.DataFrame(index=unrate.index)
    features["claims_lag1"] = icsa_monthly.reindex(features.index).shift(1)
    features["claims_lag2"] = icsa_monthly.reindex(features.index).shift(2)
    features["claims_lag3"] = icsa_monthly.reindex(features.index).shift(3)

    if not quits_df.empty:
        quits = quits_df.set_index("ts")["value"].astype(float)
        quits.index = pd.to_datetime(quits.index).to_period("M").to_timestamp()
        features["quits_lag1"] = quits.reindex(features.index).shift(1)

    if not openings_df.empty:
        openings = openings_df.set_index("ts")["value"].astype(float)
        openings.index = pd.to_datetime(openings.index).to_period("M").to_timestamp()
        features["openings_lag1"] = openings.reindex(features.index).shift(1)

    features = features.dropna()
    target = unrate.reindex(features.index).dropna()
    features = features.loc[target.index]

    if len(target) < 24:
        st.error(f"❌ Dati insufficienti per il training ({len(target)} < 24 osservazioni).")
        return

    engine_obj = LabourForecastEngine()
    try:
        engine_obj.fit(target, features)
    except Exception as exc:
        st.error(f"❌ Training fallito: {type(exc).__name__}: {str(exc)[:120]}")
        return

    future_features = features.iloc[-6:].copy()
    try:
        result = engine_obj.forecast(["1M", "3M", "6M"], future_features, "UNRATE")
    except Exception as exc:
        st.error(f"❌ Forecast fallito: {type(exc).__name__}: {str(exc)[:120]}")
        return

    now = datetime.now(_UTC).isoformat()
    n_saved = 0
    for bundle in result.bundles:
        try:
            db.execute(
                "INSERT INTO labour_forecasts "
                "(generated_at, horizon, target_metric, forecast_value, "
                "forecast_lower, forecast_upper, model_used, arima_forecast, ridge_forecast) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                [now, bundle.horizon, bundle.target_metric, bundle.point_forecast,
                 bundle.lower_10, bundle.upper_90, bundle.model_used,
                 bundle.arima_forecast, bundle.ridge_forecast],
            )
            n_saved += 1
        except Exception:
            pass

    if n_saved > 0:
        st.success(f"✅ {n_saved} previsioni UNRATE salvate (ARIMA+Ridge ensemble, n_train={result.n_train_obs}).")
        st.cache_data.clear()
        st.rerun()
    else:
        st.error("❌ Nessuna riga salvata. Verifica che la tabella labour_forecasts esista nel DB.")


def body_labour_forecasting(tokens: DesignTokens) -> None:
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

    import pandas as pd
    from shared.db.duckdb_client import get_duckdb_client

    render_section_header("🔬 Labour Forecasting — Dettaglio Modello",
        "Feature importance Ridge · Ordine ARIMA · Walk-forward accuracy · Scenario sensitivity")

    cols_top = st.columns([3, 1, 1])
    with cols_top[1]:
        if st.button("🤖 Genera previsioni", key="q9_run_forecast",
                     help="Scarica dati FRED (UNRATE, ICSA, JOLTS), addestra ensemble ARIMA+Ridge, salva forecasts nel DB"):
            with st.spinner("Training ARIMA+Ridge ensemble in corso..."):
                _run_forecast_job(st)
    with cols_top[2]:
        if st.button("🔄 Aggiorna", key="q9_refresh"):
            st.cache_data.clear()
            st.rerun()

    try:
        db = get_duckdb_client()
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
