# ruff: noqa: N999
"""Q9 — Labour Market Forecasting ★ NUOVO (v8.3 — Blocco 1).

Dashboard previsionale labour market:
  Tab 1: Forecast UNRATE  — previsione tasso disoccupazione 1M/3M/6M
  Tab 2: Forecast NFP     — previsione Non-Farm Payrolls 1M/3M/6M
  Tab 3: Forecast JOLTS   — previsione Job Openings 1M/3M/6M
  Tab 4: Forecast Claims  — previsione Claims 4wk MA 1M/3M/6M
  Tab 5: Regime forecast  — scenario regime mercato del lavoro
"""
from __future__ import annotations

__version__ = "8.3.0"
__all__ = ["body_q9_labour_forecasting"]

_HORIZONS = ["1M", "3M", "6M"]
_TARGETS = [
    ("unemployment_rate", "📉 Tasso Disoccupazione", "%"),
    ("nfp",               "💼 NFP Mensile",          "K"),
    ("quits_rate",        "🚪 Quits Rate",           "%"),
]


def body_q9_labour_forecasting(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    st.title("🔮 Labour Market — Forecasting")
    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="q9v2_refresh"):
            st.cache_data.clear()
            st.rerun()
    st.caption("ARIMA + Ridge Ensemble · Orizzonti 1M / 3M / 6M · Walk-forward validation")

    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
    except Exception as exc:
        st.error(f"DB non disponibile: {exc}")
        return

    tab_unrate, tab_nfp, tab_quits, tab_claims, tab_regime = st.tabs([
        "📉 UNRATE",
        "💼 NFP",
        "🚪 Quits Rate",
        "📋 Claims",
        "🎭 Regime",
    ])

    def _render_forecast_tab(tab, target_metric: str, label: str, unit: str) -> None:
        with tab:
            st.subheader(f"Previsione {label}")
            try:
                import pandas as pd
                rows = db.query(
                    "SELECT horizon, forecast_value, forecast_lower, forecast_upper, "
                    "model_used, arima_forecast, ridge_forecast, generated_at "
                    "FROM labour_forecasts "
                    "WHERE target_metric=? "
                    "ORDER BY generated_at DESC LIMIT 3",
                    [target_metric],
                )
                if not rows:
                    st.info(
                        f"Nessuna previsione disponibile per {target_metric}. "
                        "Eseguire LabourForecastEngine."
                    )
                    return

                for row in rows:
                    horizon, val, lo, hi, model, arima, ridge, gen_at = row
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric(
                            f"Previsione {horizon}",
                            f"{val:.2f} {unit}" if val is not None else "N/A",
                        )
                    with col2:
                        lo_s = f"{lo:.2f}" if lo is not None else "N/A"
                        hi_s = f"{hi:.2f}" if hi is not None else "N/A"
                        st.metric("CI 90%", f"[{lo_s}, {hi_s}]")
                    with col3:
                        st.metric("Modello", model or "N/A")
                    if arima is not None and ridge is not None:
                        st.caption(
                            f"ARIMA: {arima:.2f} {unit}  ·  Ridge: {ridge:.2f} {unit}  "
                            f"·  Generato: {gen_at}"
                        )
                    st.divider()

                # Historical actual vs forecast chart
                st.subheader("Storico Previsioni")
                hist_rows = db.query(
                    "SELECT generated_at, horizon, forecast_value "
                    "FROM labour_forecasts WHERE target_metric=? "
                    "ORDER BY generated_at DESC LIMIT 30",
                    [target_metric],
                )
                if hist_rows and len(hist_rows) >= 3:
                    df_h = pd.DataFrame(hist_rows, columns=["Data", "Orizzonte", "Previsione"])
                    df_h["Data"] = pd.to_datetime(df_h["Data"])
                    pivot = df_h.pivot_table(index="Data", columns="Orizzonte",
                                             values="Previsione", aggfunc="last")
                    st.line_chart(pivot, height=250)

            except Exception as exc:
                st.warning(f"Forecast non disponibile: {exc}")

    _render_forecast_tab(tab_unrate, "unemployment_rate", "Tasso Disoccupazione", "%")
    _render_forecast_tab(tab_nfp, "nfp", "NFP Mensile", "K")
    _render_forecast_tab(tab_quits, "quits_rate", "Quits Rate", "%")
    _render_forecast_tab(tab_claims, "claims_4wk_ma", "Claims 4wk MA", "K")

    # ── Tab 5: Regime Forecast ────────────────────────────────────────────────
    with tab_regime:
        st.subheader("Scenario Regime Mercato del Lavoro")
        try:
            import pandas as pd
            rows = db.query(
                "SELECT snapshot_date, regime, composite_score, jolts_score, "
                "claims_score, payroll_score, confidence "
                "FROM labour_regime ORDER BY snapshot_date DESC LIMIT 1"
            )
            if not rows:
                st.info("Nessun dato regime disponibile. Eseguire LabourRegimeClassifier.")
            else:
                r = rows[0]
                regime_icons = {
                    "tight": "🔥", "balanced": "✅", "slack": "⚠️", "deteriorating": "🚨"
                }
                regime = r[1] or "unknown"
                icon = regime_icons.get(regime, "❓")
                score = r[2]

                st.metric(
                    f"{icon} Regime Corrente",
                    regime.upper(),
                    delta=f"Score: {score:+.3f}" if score is not None else None,
                )

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    v = r[3]
                    st.metric("JOLTS Score", f"{v:+.3f}" if v is not None else "N/A")
                with col2:
                    v = r[4]
                    st.metric("Claims Score", f"{v:+.3f}" if v is not None else "N/A")
                with col3:
                    v = r[5]
                    st.metric("Payroll Score", f"{v:+.3f}" if v is not None else "N/A")
                with col4:
                    v = r[6]
                    st.metric("Confidence", f"{v:.1%}" if v is not None else "N/A")

                st.caption(f"Snapshot: {r[0]}")
                st.divider()

                # Historical regime chart
                hist_rows = db.query(
                    "SELECT snapshot_date, composite_score FROM labour_regime "
                    "ORDER BY snapshot_date DESC LIMIT 52"
                )
                if hist_rows and len(hist_rows) >= 4:
                    df_r = pd.DataFrame(hist_rows, columns=["Data", "Score"])
                    df_r = df_r.sort_values("Data").set_index("Data")
                    st.line_chart(df_r, height=200)
                    st.caption("Composite Score [-1,+1] — storico 52 settimane")

        except Exception as exc:
            st.warning(f"Regime non disponibile: {exc}")
