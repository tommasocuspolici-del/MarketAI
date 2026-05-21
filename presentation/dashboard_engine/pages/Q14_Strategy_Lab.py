# ruff: noqa: N999
"""Q14 — Strategy Lab (Blocco D).

Walk-Forward validation con progress bar + DataTable risultati.
Pattern: _load_*() pure + body_strategy_lab() Streamlit.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from presentation.ui.cache_policy import CACHE_TTL
from presentation.ui.components import EmptyState
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "1.0.0"
__all__ = ["body_strategy_lab"]

_SESSION_KEY = "q14_wf_result"
_STRATEGIES = ["MA Cross", "Momentum", "RSI", "Combined"]


def _load_wf_history(limit: int = 10) -> pd.DataFrame:
    try:
        from engine.backtesting.backtest_runner import get_backtest_runner
        df = get_backtest_runner().read_results(run_type="walk_forward", limit=limit)
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _wf_splits_to_df(wf_result) -> pd.DataFrame:
    rows = []
    for i, split in enumerate(wf_result.split_results, start=1):
        p = split.performance
        rows.append({
            "Split":          i,
            "Ticker":         split.ticker,
            "Return %":       f"{p.total_return * 100:.1f}%",
            "Sharpe":         f"{p.sharpe_ratio:.2f}",
            "Max DD %":       f"{p.max_drawdown * 100:.1f}%",
            "Win Rate %":     f"{p.win_rate * 100:.1f}%",
            "N Trade":        split.n_trades,
        })
    return pd.DataFrame(rows)


def body_strategy_lab(tokens: DesignTokens) -> None:  # pragma: no cover
    import streamlit as st

    render_section_header("🧪 Strategy Lab", "Walk-Forward validation · Robustezza out-of-sample")

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="q14_refresh"):
            st.session_state.pop(_SESSION_KEY, None)
            st.cache_data.clear()
            st.rerun()

    tab_config, tab_results, tab_history = st.tabs(["⚙️ Configura", "📊 Risultati WF", "🗂 Storico"])

    with tab_config:
        _render_config_tab(st, tokens)

    with tab_results:
        _render_results_tab(st, tokens)

    with tab_history:
        _render_history_tab(st)


def _render_config_tab(st, tokens: DesignTokens) -> None:  # pragma: no cover
    render_section_header("Configurazione Walk-Forward")

    col1, col2 = st.columns(2)
    with col1:
        ticker = st.text_input("Ticker", value="SPY", key="q14_ticker")
        strategy_name = st.selectbox("Strategia", _STRATEGIES, key="q14_strategy")
        n_splits = st.slider("Numero splits (k)", 3, 10, 5, key="q14_splits")
    with col2:
        train_pct = st.slider("Train %", 0.5, 0.8, 0.6, step=0.05, key="q14_train")
        initial_cash = st.number_input("Capitale ($)", value=10_000, min_value=1_000, step=1_000, key="q14_cash")
        days = st.slider("Periodo storico (giorni)", 365, 1825, 730, key="q14_days")

    st.info(
        f"Walk-Forward: {n_splits} splits · train {train_pct:.0%} / test {1-train_pct:.0%} · "
        f"~{int(days * (1 - train_pct) / n_splits)} giorni per split di test"
    )

    if st.button("▶ Esegui Walk-Forward", type="primary", key="q14_run"):
        _run_walk_forward(st, ticker, strategy_name, n_splits, train_pct, initial_cash, days)


def _run_walk_forward(st, ticker: str, strategy_name: str, n_splits: int,
                      train_pct: float, initial_cash: float, days: int) -> None:  # pragma: no cover
    from engine.backtesting.backtest_runner import BacktestConfig, get_backtest_runner
    from engine.backtesting.strategies.combined import CombinedStrategy
    from engine.backtesting.strategies.ma_cross import MovingAverageCrossover
    from engine.backtesting.strategies.momentum import Momentum
    from engine.backtesting.strategies.rsi import RSIMeanReversion
    from shared.db.duckdb_client import get_duckdb_client
    from shared.db.prices_repo import PricesRepository

    progress = st.progress(0, text="Caricamento dati OHLCV...")
    try:
        db = get_duckdb_client()
        repo = PricesRepository(db)
        ohlcv = repo.read_ohlcv(ticker, limit=days)
        if ohlcv.empty:
            st.error(f"❌ Nessun dato OHLCV per {ticker}.")
            progress.empty()
            return

        progress.progress(20, text="Dati caricati. Inizializzazione splits...")
        strategy_map = {
            "MA Cross": MovingAverageCrossover(),
            "Momentum": Momentum(),
            "RSI":      RSIMeanReversion(),
            "Combined": CombinedStrategy(),
        }
        strategy = strategy_map[strategy_name]
        config = BacktestConfig(
            ticker=ticker, initial_cash=float(initial_cash),
            n_splits=n_splits, train_pct=train_pct,
        )

        progress.progress(40, text=f"Walk-Forward in corso ({n_splits} splits)...")
        wf_result = get_backtest_runner().run_walk_forward(strategy, config, ohlcv=ohlcv)

        progress.progress(90, text="Aggregazione risultati...")
        st.session_state[_SESSION_KEY] = wf_result
        progress.progress(100, text="Completato!")

        agg = wf_result.aggregate_performance
        st.success(
            f"✅ Walk-Forward completato — {wf_result.n_splits} splits · "
            f"Sharpe aggregato: {agg.sharpe_ratio:.2f} · Return: {agg.total_return*100:.1f}%"
        )
        st.rerun()
    except Exception as exc:
        progress.empty()
        st.error(f"❌ Errore: {type(exc).__name__}: {str(exc)[:200]}")


def _render_results_tab(st, tokens: DesignTokens) -> None:  # pragma: no cover
    from presentation.ui.chart_theme import ChartFactory

    wf = st.session_state.get(_SESSION_KEY)
    if wf is None:
        EmptyState(
            "Nessun Walk-Forward eseguito",
            hint="Configura i parametri nel tab '⚙️ Configura' e clicca '▶ Esegui Walk-Forward'.",
        ).render()
        return

    agg = wf.aggregate_performance
    render_section_header(f"Risultati Walk-Forward — {wf.strategy_name} su {wf.ticker}")

    cols = st.columns(5)
    metrics = [
        ("Sharpe (agg.)",   f"{agg.sharpe_ratio:.2f}"),
        ("Return (agg.)",   f"{agg.total_return*100:.1f}%"),
        ("Max DD (agg.)",   f"{agg.max_drawdown*100:.1f}%"),
        ("Win Rate (agg.)", f"{agg.win_rate*100:.1f}%"),
        ("N Splits",        str(wf.n_splits)),
    ]
    for col, (label, value) in zip(cols, metrics, strict=False):
        with col:
            st.metric(label, value)

    st.divider()
    render_section_header("Risultati per Split")
    df_splits = _wf_splits_to_df(wf)
    st.dataframe(df_splits, use_container_width=True, hide_index=True)

    # Equity aggregata: stitch dei singoli split
    curves = [s.equity_curve for s in wf.split_results if not s.equity_curve.empty]
    if curves:
        import pandas as _pd
        stitched = _pd.concat(curves).reset_index()
        stitched.columns = ["date", "equity"]
        fig = ChartFactory.time_series(stitched, x_col="date", y_col="equity",
                                       title="Equity Curve aggregata (tutti gli split)")
        st.plotly_chart(fig, use_container_width=True)


def _render_history_tab(st) -> None:  # pragma: no cover
    @st.cache_data(ttl=CACHE_TTL.BACKTESTING)
    def _cached() -> pd.DataFrame:
        return _load_wf_history()

    df = _cached()
    if df.empty:
        EmptyState("Nessun Walk-Forward salvato", hint="Esegui il primo Walk-Forward per popolare lo storico.").render()
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)


if __name__ == "__main__":  # pragma: no cover
    render_page("Strategy Lab", "🧪", body_strategy_lab)
