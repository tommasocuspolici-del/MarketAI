"""T1 — Backtesting v9.0 (Roadmap v3.0 Settimana 10 Final Integration).

Integra: DSLStrategy, CompositeSignalStrategy, BacktestRunner, StressTestRunner.

Tab:  🧪 Esegui | 📊 Risultati | ⚡ Stress | 📋 Storia
"""
from __future__ import annotations

__version__ = "9.0.0"
__all__ = ["body_t1_backtesting"]

_STRATEGIES = ["MA Cross (20/50)", "RSI (14)", "Momentum (20)", "DSL custom"]
_TICKERS    = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "GLD", "USO"]


def body_t1_backtesting(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()
    st.title("🧪 Backtesting — v9.0")
    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="t1_refresh"):
            st.cache_data.clear()
            st.rerun()
    tab_run, tab_res, tab_stress, tab_hist = st.tabs(
        ["🧪 Esegui", "📊 Risultati", "⚡ Stress", "📋 Storia"]
    )
    with tab_run:    _run(st, tokens)
    with tab_res:    _results(st, tokens)
    with tab_stress: _stress(st, tokens)
    with tab_hist:   _history(st, tokens)


def _build_strategy(strategy_name: str, dsl_expr: str = ""):
    """Factory: crea la Strategy dal nome selezionato."""
    from engine.backtesting.strategy_builder import build_strategy_from_dsl
    from engine.backtesting.strategies.ma_cross import MovingAverageCrossover
    from engine.backtesting.strategies.rsi import RSIStrategy
    from engine.backtesting.strategies.momentum import MomentumStrategy
    if strategy_name == "MA Cross (20/50)":
        return MovingAverageCrossover(fast=20, slow=50)
    if strategy_name == "RSI (14)":
        return RSIStrategy(period=14)
    if strategy_name == "Momentum (20)":
        return MomentumStrategy(lookback=20)
    if strategy_name == "DSL custom":
        if not dsl_expr.strip():
            from shared.exceptions import BacktestError
            raise BacktestError("Inserisci un'espressione DSL.")
        return build_strategy_from_dsl(dsl_expr.strip())
    return MovingAverageCrossover(fast=20, slow=50)


def _load_ohlcv(ticker: str):
    from shared.db.prices_repo import get_prices_repository
    from shared.types import TimeFrame
    repo = get_prices_repository()
    df = repo.read_ohlcv(ticker=ticker, exchange="NASDAQ",
                          timeframe=TimeFrame.D1, limit=500)
    return df


def _run(st, tokens) -> None:  # pragma: no cover
    st.subheader("Configura e avvia il backtest")
    c1, c2, c3 = st.columns([2, 2, 1])
    ticker   = c1.selectbox("Ticker", _TICKERS, key="t1_ticker")
    strategy = c2.selectbox("Strategia", _STRATEGIES, key="t1_strategy")
    wf_mode  = c3.checkbox("Walk-forward", key="t1_wf")

    dsl_expr = ""
    if strategy == "DSL custom":
        dsl_expr = st.text_input(
            "Espressione DSL", "RSI(close, 14) > 50", key="t1_dsl",
            help="es: EMA(close,20) > close | MACD(close,12,26,9)",
        )
        st.caption(
            "Funzioni DSL disponibili: `EMA`, `SMA`, `RSI`, `MACD`, "
            "`STD`, `MAX`, `MIN`, `ABS`, `LOG`, `PCT_CHANGE` + operatori."
        )

    c_fees, c_slip, c_cash = st.columns(3)
    fees = c_fees.number_input("Fees %", 0.01, 2.0, 0.10, 0.01, key="t1_fees") / 100
    slip = c_slip.number_input("Slippage %", 0.01, 2.0, 0.10, 0.01, key="t1_slip") / 100
    cash = c_cash.number_input("Capitale $", 1_000, 1_000_000, 10_000, 1_000, key="t1_cash")

    if not st.button("▶ Esegui", key="t1_run_btn"):
        st.info("Configura e clicca **Esegui**.")
        return

    try:
        from engine.backtesting.backtest_runner import BacktestConfig, BacktestRunner
        strat  = _build_strategy(strategy, dsl_expr)
        df     = _load_ohlcv(ticker)
        if df is None or df.empty:
            st.error(f"Nessun dato OHLCV per **{ticker}**.")
            return

        config = BacktestConfig(ticker=ticker, initial_cash=float(cash),
                                fees=fees, slippage=slip)
        runner = BacktestRunner()

        with st.spinner("…"):
            if wf_mode:
                wf = runner.run_walk_forward(strat, config, ohlcv=df)
                perf   = wf.aggregate_performance
                equity = wf.split_results[-1].equity_curve if wf.split_results else None
                st.caption(f"Walk-forward: {wf.n_splits} split completati")
            else:
                res    = runner.run(strat, config, ohlcv=df)
                perf   = res.performance
                equity = res.equity_curve

        st.session_state.update({
            "t1_perf": perf, "t1_equity": equity,
            "t1_ticker": ticker, "t1_strat": strategy,
        })
        c_s, c_d, c_r = st.columns(3)
        c_s.metric("Sharpe",       f"{perf.sharpe_ratio:.3f}")
        c_d.metric("Max Drawdown", f"{perf.max_drawdown:.1%}")
        c_r.metric("Total Return", f"{perf.total_return:.1%}")
        st.success("✅ Backtest completato — vedi tab **📊 Risultati**")
    except Exception as exc:
        st.error(f"Errore: {exc}")


def _results(st, tokens) -> None:  # pragma: no cover
    equity = st.session_state.get("t1_equity")
    perf   = st.session_state.get("t1_perf")
    if equity is None:
        st.info("Esegui prima un backtest dalla tab **🧪 Esegui**.")
        return
    import plotly.graph_objects as go
    bar_col = tokens.colors.positive if float(equity.iloc[-1]) >= float(equity.iloc[0]) else tokens.colors.negative
    fig = go.Figure()
    fig.add_scatter(x=list(range(len(equity))), y=equity.values, mode="lines",
                    line={"color": bar_col, "width": 2}, name="Equity")
    fig.add_hline(y=float(equity.iloc[0]), line_dash="dot",
                  line_color=tokens.colors.text_muted, annotation_text="Start")
    fig.update_layout(
        title=f"Equity Curve — {st.session_state.get('t1_ticker', '?')} ({st.session_state.get('t1_strat', '?')})",
        height=380, template=tokens.plotly.template,
        paper_bgcolor=tokens.plotly.paper_bgcolor,
        plot_bgcolor=tokens.plotly.plot_bgcolor,
        font={"family": tokens.plotly.font_family, "color": tokens.plotly.font_color},
        margin={"l": 0, "r": 0, "t": 50, "b": 0},
    )
    st.plotly_chart(fig, use_container_width=True)
    if perf:
        cols = st.columns(4)
        cols[0].metric("Sharpe",      f"{perf.sharpe_ratio:.3f}")
        cols[1].metric("Max Drawdown",f"{perf.max_drawdown:.1%}")
        cols[2].metric("Total Return",f"{perf.total_return:.1%}")
        cols[3].metric("Volatility",  f"{getattr(perf, 'volatility', 0):.1%}")


def _stress(st, tokens) -> None:  # pragma: no cover
    st.subheader("⚡ Stress Test — 5 Scenari Forward-Looking")
    st.caption("**Regola 24**: ogni stress test include scenari sintetici forward-looking.")
    ticker   = st.selectbox("Ticker", _TICKERS, key="t1_s_ticker")
    strategy = st.selectbox("Strategia", _STRATEGIES[:3], key="t1_s_strat")
    if not st.button("⚡ Esegui tutti gli scenari", key="t1_s_run"):
        return
    try:
        from engine.stress_test.forward_scenarios import StressTestRunner
        df = _load_ohlcv(ticker)
        if df is None or df.empty:
            st.error(f"Nessun dato per {ticker}.")
            return
        strat   = _build_strategy(strategy)
        runner  = StressTestRunner()
        with st.spinner("Esecuzione 5 scenari…"):
            results = runner.run_all_scenarios(strat, df, ticker=ticker)
            compare = runner.compare_scenarios(results)
        st.dataframe(compare, use_container_width=True)
        import plotly.graph_objects as go
        _COLORS = {
            "base": tokens.colors.neutral,
            "goldilocks": tokens.colors.positive,
            "recession": tokens.colors.negative,
            "inflation_shock": tokens.colors.warning,
            "credit_crisis": "#FF6600",
        }
        fig = go.Figure()
        for scen, res in results.items():
            fig.add_scatter(
                x=list(range(len(res.equity_curve))), y=res.equity_curve.values,
                name=scen.replace("_", " ").title(),
                line={"color": _COLORS.get(scen, tokens.colors.accent_primary), "width": 1.5},
            )
        fig.update_layout(
            title="Equity per Scenario", height=320,
            template=tokens.plotly.template,
            paper_bgcolor=tokens.plotly.paper_bgcolor,
            plot_bgcolor=tokens.plotly.plot_bgcolor,
            font={"family": tokens.plotly.font_family, "color": tokens.plotly.font_color},
            legend={"orientation": "h"}, margin={"l": 0, "r": 0, "t": 40, "b": 0},
        )
        st.plotly_chart(fig, use_container_width=True)
    except Exception as exc:
        st.error(f"Errore: {exc}")


def _history(st, tokens) -> None:  # pragma: no cover
    st.subheader("📋 Cronologia backtest")
    try:
        from engine.backtesting.backtest_runner import BacktestRunner
        df = BacktestRunner().read_results(limit=30)
        if df.empty:
            st.info("Nessun risultato. Esegui un backtest dalla tab 🧪.")
        else:
            st.dataframe(df, use_container_width=True)
    except Exception as exc:
        st.warning(f"Storia non disponibile: {exc}")
