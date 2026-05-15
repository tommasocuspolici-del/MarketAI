# ruff: noqa: N999
"""E9 — Forecasting (v7.1.2 hotfix).

Risolve "previsioni con random data" segnalato in ULTERIORI_ERRORI.txt:
la versione precedente generava 3 scenari da ``np.random.default_rng(99)``
indipendenti dai dati di mercato.

Ora la pagina:
  - Fetcha OHLCV reale da yfinance (riusando ``E2_Equities.fetch_ohlcv_yfinance``).
  - Calcola drift e volatility realizzati sull'ultimo anno.
  - Usa ``SimpleForecaster`` (GBM 3-scenari) per i path forward.
  - Mostra le metriche storiche (vol annualizzata, drift annualizzato)
    per dare contesto, e dichiara apertamente i limiti del modello.
  - Fallback graceful se dati insufficienti.

Limitazione dichiarata in UI: SimpleForecaster e' GBM parametrico —
forecasting econometrico (ARIMA/Prophet) e' in roadmap settimane 4-7.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from engine.forecasting import ForecastResult, SimpleForecaster
from presentation.dashboard_engine.pages.E2_Equities import fetch_ohlcv_yfinance
from presentation.ui.cache_policy import CACHE_TTL
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.1.2"

__all__ = ["body_forecasting"]

_DEFAULT_TICKERS: tuple[str, ...] = (
    "^GSPC",     # S&P 500
    "^NDX",      # Nasdaq 100
    "AAPL",
    "MSFT",
    "GOOGL",
    "TSLA",
    "GC=F",      # Gold
    "CL=F",      # WTI
    "BTC-USD",   # Bitcoin
)

_HORIZON_OPTIONS: dict[str, int] = {
    "30 giorni": 30,
    "60 giorni": 60,
    "90 giorni": 90,
    "180 giorni": 180,
}


def _cached_forecast(
    ticker: str, horizon_days: int
) -> tuple[ForecastResult | None, str | None]:
    """Wrapper con cache: ritorna (result, error_message)."""
    try:
        import streamlit as st

        @st.cache_data(ttl=CACHE_TTL.BACKTESTING, show_spinner=False)
        def _fn(t: str, h: int) -> tuple[ForecastResult | None, str | None]:
            return _forecast_inner(t, h)

        return _fn(ticker, horizon_days)
    except ImportError:  # pragma: no cover
        return _forecast_inner(ticker, horizon_days)


def _forecast_inner(
    ticker: str, horizon_days: int
) -> tuple[ForecastResult | None, str | None]:
    """Logica core: fetch + forecast. Separata per testabilita'."""
    df = fetch_ohlcv_yfinance(ticker, period="2y")
    if df.empty:
        return None, (
            f"Nessun dato per `{ticker}`: ticker errato, yfinance non "
            "installato, o Yahoo non raggiungibile."
        )
    if len(df) < 30:
        return None, (
            f"Storico insufficiente per `{ticker}` ({len(df)} barre, "
            "richieste >= 30)."
        )
    forecaster = SimpleForecaster()
    try:
        result = forecaster.forecast(
            close_prices=df["close"].to_numpy(),
            ticker=ticker,
            horizon_days=horizon_days,
        )
    except ValueError as exc:
        return None, str(exc)
    return result, None


def _render_forecast_chart(  # pragma: no cover -- Streamlit
    tokens: DesignTokens, st_module, result: ForecastResult
) -> None:
    """Disegna i 3 scenari + linea ultimo prezzo."""
    try:
        import plotly.graph_objects as go
    except ImportError:
        return

    # Recupera scenari nominati
    scenario_map = {sc.name: sc for sc in result.scenarios}
    pessim = scenario_map["pessimistic"]
    base = scenario_map["base"]
    optim = scenario_map["optimistic"]

    days = np.arange(1, result.horizon_days + 1)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=days,
            y=optim.path,
            name="Ottimistico (+1.65σ)",
            line={"color": tokens.colors.positive, "dash": "dot"},
            hovertemplate="Day %{x}: %{y:,.2f}<extra>Ottimistico</extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=days,
            y=base.path,
            name="Base",
            line={"color": tokens.colors.accent_primary, "width": 3},
            hovertemplate="Day %{x}: %{y:,.2f}<extra>Base</extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=days,
            y=pessim.path,
            name="Pessimistico (−1.65σ)",
            line={"color": tokens.colors.negative, "dash": "dot"},
            hovertemplate="Day %{x}: %{y:,.2f}<extra>Pessimistico</extra>",
        )
    )
    # Linea orizzontale con ultimo prezzo
    fig.add_hline(
        y=result.last_price,
        line_dash="dash",
        line_color=tokens.colors.text_secondary,
        annotation_text=f"Ultimo: {result.last_price:,.2f}",
        annotation_position="top left",
    )
    fig.update_layout(
        template=tokens.plotly.template,
        paper_bgcolor=tokens.plotly.paper_bgcolor,
        plot_bgcolor=tokens.plotly.plot_bgcolor,
        height=tokens.plotly.height_md,
        xaxis_title="Giorni forward",
        yaxis_title="Prezzo",
        font={
            "family": tokens.plotly.font_family,
            "color": tokens.plotly.font_color,
        },
    )
    st_module.plotly_chart(fig, use_container_width=True)


def body_forecasting(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

    render_section_header(
        "🔮 Forecast 3-scenari",
        "Pessimistico · Base · Ottimistico — modello GBM su dati reali yfinance",
    )

    cols = st.columns([2, 2, 2, 1])
    with cols[0]:
        ticker_select = st.selectbox(
            "Ticker",
            options=_DEFAULT_TICKERS,
            index=0,
            key="e9_ticker",
        )
    with cols[1]:
        custom_ticker = st.text_input(
            "...o custom",
            placeholder="Es. NFLX",
            key="e9_custom",
        ).strip().upper()
    with cols[2]:
        horizon_label = st.selectbox(
            "Orizzonte",
            options=list(_HORIZON_OPTIONS.keys()),
            index=1,
            key="e9_horizon",
        )
    with cols[3]:
        st.write("")
        st.write("")
        if st.button("🔄 Aggiorna", key="e9_refresh"):
            st.cache_data.clear()
            st.rerun()

    ticker = custom_ticker if custom_ticker else ticker_select
    horizon_days = _HORIZON_OPTIONS[horizon_label]

    with st.spinner(f"Calcolo forecast {ticker} ({horizon_label})..."):
        result, err = _cached_forecast(ticker, horizon_days)

    if err is not None or result is None:
        st.error(f"❌ {err or 'Forecast non disponibile.'}")
        st.info(
            "💡 Verifica il ticker, lo storico richiesto (>= 30 barre), "
            "e che `yfinance` sia installato. Vai a **📡 API Health** per dettagli."
        )
        return

    # KPI riepilogativi
    cols_kpi = st.columns(4)
    cols_kpi[0].metric("Ultimo prezzo", f"{result.last_price:,.2f}")
    cols_kpi[1].metric(
        "Volatilità annualizzata",
        f"{result.historical_volatility_annualized * 100:.2f}%",
    )
    cols_kpi[2].metric(
        "Drift annualizzato",
        f"{result.historical_drift_annualized * 100:+.2f}%",
    )
    cols_kpi[3].metric(
        "Storico usato",
        f"{result.historical_days} giorni",
    )

    _render_forecast_chart(tokens, st, result)

    # Tabella scenari
    st.write("**Returns attesi a fine orizzonte:**")
    rows = []
    label_map = {
        "pessimistic": "📉 Pessimistico (−1.65σ)",
        "base": "📊 Base (drift osservato)",
        "optimistic": "📈 Ottimistico (+1.65σ)",
    }
    for sc in result.scenarios:
        rows.append(
            {
                "Scenario": label_map.get(sc.name, sc.name),
                "Drift annualizzato": f"{sc.annualized_drift * 100:+.2f}%",
                "Prezzo finale": f"{sc.path[-1]:,.2f}",
                "Return totale": f"{sc.expected_return_pct:+.2f}%",
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)

    # Disclaimer modellistico onesto
    with st.expander("ℹ️ Limitazioni del modello", expanded=False):
        st.markdown(
            "**SimpleForecaster** e' un modello GBM (geometric Brownian motion) "
            "parametrico, pensato per esplorazione visuale. Limiti:\n\n"
            "- Assume returns log-normali e indipendenti — falso per la maggior "
            "parte degli asset reali (volatility clustering, fat tails).\n"
            "- La volatility forecast e' uguale alla realizzata (no GARCH).\n"
            "- Non modella regime changes, eventi macro, o catalizzatori specifici.\n"
            "- Drift basato sul solo storico recente: previsioni a lungo termine "
            "perdono affidabilita' rapidamente.\n\n"
            "Modelli econometrici piu' robusti (ARIMA, Prophet) con backtesting "
            "walk-forward sono in roadmap (settimane 4-7 della Roadmap Unificata 2.0)."
        )


if __name__ == "__main__":  # pragma: no cover
    render_page("Forecasting", "🔮", body_forecasting)
