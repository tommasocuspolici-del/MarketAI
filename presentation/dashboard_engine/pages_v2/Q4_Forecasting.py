# ruff: noqa: N999
"""Q4 Forecasting (v8.1) — prezzi futuri da labour_forecasts + FRED growth series."""
from __future__ import annotations

__version__ = "8.1.0"
__all__ = ["body_q4_forecasting"]


def body_q4_forecasting(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    st.title("🔬 Analisi — Forecasting (3 scenari)")
    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="q4_refresh"):
            st.cache_data.clear()
            st.rerun()

    # ── Labour Forecasts (da DB) ──────────────────────────────────────────
    st.subheader("👷 Labour Market Forecasts (ARIMA+Ridge)")

    @st.cache_data(ttl=3600)
    def _load_labour_forecasts():
        from shared.db.duckdb_client import get_duckdb_client
        try:
            db = get_duckdb_client()
            rows = db.query(
                "SELECT horizon, target_metric, forecast_value, forecast_lower, "
                "forecast_upper, model_used, generated_at "
                "FROM labour_forecasts ORDER BY generated_at DESC, horizon"
            )
            return rows or []
        except Exception:
            return []

    rows = _load_labour_forecasts()
    if rows:
        import pandas as pd
        df = pd.DataFrame(rows, columns=[
            "Orizzonte", "Metrica", "Forecast", "Lower 80%", "Upper 80%", "Modello", "Generato"
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption("Generato da Q9 Labour Forecasting con ARIMA+Ridge su dati FRED")
    else:
        st.info("Nessun forecast disponibile — vai su Q9 Labour Forecasting e premi '🤖 Genera previsioni'.")

    st.divider()

    # ── FRED Growth Series ────────────────────────────────────────────────
    st.subheader("📈 Trend Macroeconomici — Dati FRED Recenti")

    @st.cache_data(ttl=3600)
    def _load_macro_trends():
        from engine.market_data.fred_simple_client import FredSimpleClient
        fred = FredSimpleClient()
        if not fred.has_api_key:
            return None, "FRED_API_KEY non configurata in .env"
        results = {}
        series_map = {
            "GDP Growth": "A191RL1Q225SBEA",
            "UNRATE": "UNRATE",
            "CPI YoY": "CPIAUCSL",
            "Fed Funds Rate": "FEDFUNDS",
        }
        for label, series_id in series_map.items():
            try:
                df = fred.fetch_series(series_id, limit=24)
                if df is not None and not df.empty:
                    results[label] = df
            except Exception:
                pass
        return results, None

    macro_data, err = _load_macro_trends()
    if err:
        st.warning(f"⚠️ FRED non disponibile: {err}")
    elif macro_data:
        import pandas as pd
        cols = st.columns(2)
        for i, (label, df) in enumerate(macro_data.items()):
            with cols[i % 2]:
                st.markdown(f"**{label}**")
                if not df.empty:
                    latest = df["value"].iloc[-1]
                    prev = df["value"].iloc[-2] if len(df) >= 2 else latest
                    delta = latest - prev
                    st.metric(label, f"{latest:.2f}", delta=f"{delta:+.2f}")
                    st.line_chart(df.set_index("ts")["value"].tail(12), height=120)
    else:
        st.info("Nessun dato FRED disponibile.")
