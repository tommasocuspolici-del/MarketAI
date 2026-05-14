# ruff: noqa: N999
"""E12 — Backtesting (v7.1.2 hotfix).

Risolve "backtest con dati mock" segnalato in ULTERIORI_ERRORI.txt:
la versione precedente usava ``build_mock_backtest()`` con seed=42, mostrando
sempre lo stesso identico risultato indipendentemente dai parametri.

Ora la pagina:
  - Selettore ticker (predefinito o custom).
  - 3 strategie: MA Cross, RSI Mean Reversion, Momentum.
  - Fetch storico reale via yfinance (5 anni di OHLCV daily).
  - Backtest reale con commissioni + slippage (Regola 23).
  - Equity curve, drawdown, Sharpe, MAR ratio dalle metriche reali.
  - Fallback graceful se dati o dipendenze mancano.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from engine.backtesting import BacktestEngine, BacktestResult
from engine.backtesting.engine import MIN_FEES, MIN_SLIPPAGE
from engine.backtesting.strategies import (
    Momentum,
    MovingAverageCrossover,
    RSIMeanReversion,
)
from engine.backtesting.strategy import Strategy
from presentation.dashboard_engine.pages.E2_Equities import fetch_ohlcv_yfinance
from presentation.ui.components.backtest_report import render_backtest_report
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.1.2"

__all__ = ["body_backtesting"]


_DEFAULT_TICKERS: tuple[str, ...] = (
    "^GSPC",
    "^NDX",
    "AAPL",
    "MSFT",
    "GOOGL",
    "TSLA",
    "GC=F",
    "BTC-USD",
)

_PERIOD_OPTIONS: dict[str, str] = {
    "2 anni": "2y",
    "5 anni": "5y",
    "10 anni": "10y",
    "Max": "max",
}

_STRATEGIES = ("MA Cross", "RSI Mean Reversion", "Momentum")


def _build_strategy(
    name: str,
    *,
    ma_fast: int,
    ma_slow: int,
    rsi_period: int,
    rsi_oversold: float,
    rsi_overbought: float,
    momentum_lookback: int,
) -> Strategy:
    """Factory che costruisce la strategia selezionata con i parametri UI."""
    if name == "MA Cross":
        return MovingAverageCrossover(fast=ma_fast, slow=ma_slow)
    if name == "RSI Mean Reversion":
        return RSIMeanReversion(
            period=rsi_period,
            oversold=rsi_oversold,
            overbought=rsi_overbought,
        )
    if name == "Momentum":
        return Momentum(lookback=momentum_lookback, require_breakout=True)
    raise ValueError(f"Strategia non riconosciuta: {name}")


def _cached_fetch(ticker: str, period: str) -> pd.DataFrame:
    """Fetch con cache Streamlit."""
    try:
        import streamlit as st

        @st.cache_data(ttl=900, show_spinner=False)
        def _fn(t: str, p: str) -> pd.DataFrame:
            return fetch_ohlcv_yfinance(t, p)

        return _fn(ticker, period)
    except ImportError:  # pragma: no cover
        return fetch_ohlcv_yfinance(ticker, period)


def _prepare_for_backtest(df: pd.DataFrame) -> pd.DataFrame:
    """BacktestEngine.run richiede DataFrame con index temporale e colonna 'close'.

    Il fetcher in E2 restituisce 'ts' come colonna; qui la promuoviamo a indice.
    """
    if df.empty:
        return df
    if "ts" in df.columns:
        prepared = df.set_index("ts").sort_index()
    else:
        prepared = df.copy()
    return prepared


def body_backtesting(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

    render_section_header(
        "🧪 Backtest Strategy",
        "Strategie classiche su dati reali yfinance · commissioni e slippage inclusi (Regola 23)",
    )

    # ── Selezione ticker e periodo ────────────────────────────────────────
    cols_top = st.columns([2, 2, 2, 1])
    with cols_top[0]:
        ticker_select = st.selectbox(
            "Ticker",
            options=_DEFAULT_TICKERS,
            index=0,
            key="e12_ticker",
        )
    with cols_top[1]:
        custom_ticker = st.text_input(
            "...o custom",
            placeholder="Es. ENI.MI",
            key="e12_custom",
        ).strip().upper()
    with cols_top[2]:
        period_label = st.selectbox(
            "Periodo storico",
            options=list(_PERIOD_OPTIONS.keys()),
            index=1,
            key="e12_period",
        )
    with cols_top[3]:
        st.write("")
        st.write("")
        if st.button("🔄 Ricarica", key="e12_refresh"):
            st.cache_data.clear()
            st.rerun()

    ticker = custom_ticker if custom_ticker else ticker_select
    period = _PERIOD_OPTIONS[period_label]

    # ── Selezione strategia + parametri ───────────────────────────────────
    st.divider()
    cols_strat = st.columns(4)
    with cols_strat[0]:
        strategy_name = st.selectbox(
            "Strategia",
            options=_STRATEGIES,
            index=0,
            key="e12_strat",
        )

    # Parametri condizionali per strategia (default ragionevoli)
    ma_fast = ma_slow = rsi_period = momentum_lookback = 0
    rsi_oversold = rsi_overbought = 0.0

    if strategy_name == "MA Cross":
        with cols_strat[1]:
            ma_fast = int(
                st.number_input(
                    "Fast SMA",
                    min_value=2,
                    max_value=100,
                    value=20,
                    key="e12_ma_fast",
                )
            )
        with cols_strat[2]:
            ma_slow = int(
                st.number_input(
                    "Slow SMA",
                    min_value=10,
                    max_value=300,
                    value=50,
                    key="e12_ma_slow",
                )
            )
    elif strategy_name == "RSI Mean Reversion":
        with cols_strat[1]:
            rsi_period = int(
                st.number_input(
                    "Periodo RSI",
                    min_value=2,
                    max_value=50,
                    value=14,
                    key="e12_rsi_period",
                )
            )
        with cols_strat[2]:
            rsi_oversold = float(
                st.number_input(
                    "Oversold",
                    min_value=5.0,
                    max_value=49.0,
                    value=30.0,
                    step=1.0,
                    key="e12_rsi_oversold",
                )
            )
        with cols_strat[3]:
            rsi_overbought = float(
                st.number_input(
                    "Overbought",
                    min_value=51.0,
                    max_value=95.0,
                    value=70.0,
                    step=1.0,
                    key="e12_rsi_overbought",
                )
            )
    elif strategy_name == "Momentum":
        with cols_strat[1]:
            momentum_lookback = int(
                st.number_input(
                    "Lookback (giorni)",
                    min_value=10,
                    max_value=252,
                    value=60,
                    key="e12_mom_lookback",
                )
            )

    # Validazione parametri MA Cross
    if strategy_name == "MA Cross" and ma_fast >= ma_slow:
        st.error("❌ Fast SMA deve essere strettamente minore di Slow SMA.")
        return

    cols_run = st.columns([1, 3])
    with cols_run[0]:
        run_clicked = st.button(
            "▶️ Esegui Backtest",
            type="primary",
            use_container_width=True,
            key="e12_run",
        )

    if not run_clicked:
        st.info(
            "Seleziona ticker, periodo e strategia, poi premi **Esegui Backtest**. "
            f"I dati vengono fetchati live da yfinance e il backtest applica "
            f"commissioni del {MIN_FEES * 100:.2f}% per trade + "
            f"slippage del {MIN_SLIPPAGE * 100:.2f}% (minimi Rule 23 invariabili)."
        )
        return

    # ── Esecuzione backtest ───────────────────────────────────────────────
    with st.spinner(f"Carico storico {ticker} ({period_label})..."):
        df_raw = _cached_fetch(ticker, period)

    if df_raw.empty:
        st.error(
            f"❌ **Nessun dato OHLCV per `{ticker}`.** Verifica il ticker e "
            "che yfinance sia installato. Vai a **📡 API Health** per dettagli."
        )
        return

    df = _prepare_for_backtest(df_raw)
    if len(df) < 100:
        st.warning(
            f"⚠️ Storico molto breve ({len(df)} barre): risultati di backtest "
            "poco significativi statisticamente."
        )

    try:
        strategy = _build_strategy(
            strategy_name,
            ma_fast=ma_fast,
            ma_slow=ma_slow,
            rsi_period=rsi_period,
            rsi_oversold=rsi_oversold,
            rsi_overbought=rsi_overbought,
            momentum_lookback=momentum_lookback,
        )
    except ValueError as exc:
        st.error(f"❌ Strategia non valida: {exc}")
        return

    engine = BacktestEngine(
        initial_cash=10_000.0,
        # v7.2 (fix B6): usiamo le costanti minime esportate da
        # engine.backtesting.engine. Il vecchio slippage=0.0005 era SOTTO
        # MIN_SLIPPAGE=0.001 (Rule 23 invariabile) → BacktestError runtime.
        fees=MIN_FEES,
        slippage=MIN_SLIPPAGE,
    )

    try:
        with st.spinner(f"Eseguo backtest {strategy.name} su {ticker}..."):
            result: BacktestResult = engine.run(df, strategy, ticker=ticker)
    except Exception as exc:  # noqa: BLE001 -- vogliamo mostrare l'errore in UI
        st.error(f"❌ Errore durante il backtest: {exc}")
        return

    st.success(
        f"✅ Backtest completato: **{strategy.name}** su **{ticker}** "
        f"({len(df)} barre, {period_label})"
    )

    # Render report (componente esistente — equity curve + KPI)
    render_backtest_report(tokens, result)

    st.caption(
        f"📌 Fees: {MIN_FEES * 100:.2f}% per trade · "
        f"Slippage: {MIN_SLIPPAGE * 100:.2f}% · Anti-lookahead: signal "
        "applicato a t+1 (Regola 23 · MIN_FEES, MIN_SLIPPAGE rispettati)"
    )


if __name__ == "__main__":  # pragma: no cover
    render_page("Backtesting", "🧪", body_backtesting)
