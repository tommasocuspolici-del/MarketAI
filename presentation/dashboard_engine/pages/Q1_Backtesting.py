# ruff: noqa: N999
"""Q1 — Backtesting Engine (Blocco D).

Pattern: _load_*() pure + body_backtesting() Streamlit.
3 tab: Esegui · Risultati · Storico
"""
from __future__ import annotations

import pandas as pd

from presentation.ui.cache_policy import CACHE_TTL
from presentation.ui.components import EmptyState
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page
from presentation.ui.session_keys import SK

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "1.0.0"
__all__ = ["body_backtesting"]

_STRATEGIES = ["MA Cross", "Momentum", "RSI", "Combined"]


def _get_available_strategies() -> list[str]:
    return list(_STRATEGIES)


def _load_backtest_history(limit: int = 20) -> pd.DataFrame:
    try:
        from engine.backtesting.backtest_runner import get_backtest_runner
        return get_backtest_runner().read_results(limit=limit)
    except Exception:
        return pd.DataFrame()


def body_backtesting(tokens: DesignTokens) -> None:  # pragma: no cover
    import streamlit as st

    render_section_header("⚡ Backtesting Engine", "Testa strategie su dati storici OHLCV")

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="q1_refresh"):
            st.cache_data.clear()
            st.rerun()

    tab_run, tab_results, tab_history = st.tabs(["▶ Esegui", "📊 Risultati", "🗂 Storico"])

    with tab_run:
        _render_run_tab(st, tokens)

    with tab_results:
        _render_results_tab(st, tokens)

    with tab_history:
        _render_history_tab(st)


def _render_run_tab(st, tokens: DesignTokens) -> None:  # pragma: no cover
    from engine.backtesting.backtest_runner import BacktestConfig, get_backtest_runner
    from engine.backtesting.strategies.ma_cross import MovingAverageCrossover
    from engine.backtesting.strategies.momentum import Momentum
    from engine.backtesting.strategies.rsi import RSIMeanReversion
    from engine.backtesting.strategies.combined import CombinedStrategy
    from shared.db.prices_repo import PricesRepository
    from shared.db.duckdb_client import get_duckdb_client

    col1, col2 = st.columns(2)
    with col1:
        ticker = st.text_input("Ticker", value="SPY", key="q1_ticker")
        strategy_name = st.selectbox("Strategia", _get_available_strategies(), key="q1_strategy")
    with col2:
        initial_cash = st.number_input("Capitale iniziale ($)", value=10_000, min_value=1_000, step=1_000, key="q1_cash")
        days = st.slider("Periodo storico (giorni)", 90, 1825, 365, key="q1_days")

    if st.button("▶ Esegui backtest", type="primary", key="q1_run"):
        with st.spinner("Calcolo in corso..."):
            try:
                db = get_duckdb_client()
                repo = PricesRepository(db)
                ohlcv = repo.read_ohlcv(ticker, limit=days)
                if ohlcv.empty:
                    st.error(f"❌ Nessun dato OHLCV per {ticker}. Popola il DB prima.")
                    return

                strategy_map = {
                    "MA Cross": MovingAverageCrossover(),
                    "Momentum": Momentum(),
                    "RSI": RSIMeanReversion(),
                    "Combined": CombinedStrategy(),
                }
                strategy = strategy_map[strategy_name]
                config = BacktestConfig(ticker=ticker, initial_cash=float(initial_cash))
                result = get_backtest_runner().run(strategy, config, ohlcv=ohlcv)
                st.session_state[SK.BACKTEST_RESULT] = result
                st.success(f"✅ Backtest completato — {result.n_trades} trade")
                st.rerun()
            except Exception as exc:
                st.error(f"❌ Errore: {type(exc).__name__}: {str(exc)[:200]}")


def _render_results_tab(st, tokens: DesignTokens) -> None:  # pragma: no cover
    from presentation.ui.chart_theme import ChartFactory

    result = st.session_state.get(SK.BACKTEST_RESULT)
    if result is None:
        EmptyState(
            "Nessun backtest eseguito",
            hint="Vai al tab 'Esegui', configura i parametri e clicca '▶ Esegui backtest'.",
        ).render()
        return

    p = result.performance
    render_section_header(f"Risultati — {result.strategy_name} su {result.ticker}")

    cols = st.columns(6)
    kpis = [
        ("Sharpe", f"{p.sharpe_ratio:.2f}", ""),
        ("Max DD", f"{p.max_drawdown*100:.1f}%", ""),
        ("Win Rate", f"{p.win_rate*100:.1f}%", ""),
        ("Return", f"{p.total_return*100:.1f}%", ""),
        ("Trade", str(result.n_trades), ""),
        ("Calmar", f"{p.calmar_ratio:.2f}", ""),
    ]
    for col, (label, value, unit) in zip(cols, kpis):
        with col:
            st.metric(label, value)

    equity = result.equity_curve
    if not equity.empty:
        df_eq = equity.reset_index()
        df_eq.columns = ["date", "equity"]
        fig = ChartFactory.time_series(df_eq, x="date", y="equity", title="Equity Curve")
        st.plotly_chart(fig, use_container_width=True)


def _render_history_tab(st) -> None:  # pragma: no cover
    @st.cache_data(ttl=CACHE_TTL.BACKTESTING)
    def _cached_history() -> pd.DataFrame:
        return _load_backtest_history()

    df = _cached_history()
    if df.empty:
        EmptyState("Nessun backtest salvato", hint="Esegui il primo backtest per popolare lo storico.").render()
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)


if __name__ == "__main__":  # pragma: no cover
    render_page("Backtesting", "⚡", body_backtesting)
