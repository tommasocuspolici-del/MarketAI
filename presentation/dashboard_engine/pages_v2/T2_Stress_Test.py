"""T2 — Stress Test v9.0 (Roadmap v3.0 Settimana 10 Final Integration).

Integra: ForwardScenarioGenerator, StressTestRunner, compare_scenarios.

Regola 24: ogni stress test include scenari sintetici forward-looking.
           NON solo scenari storici — questo modulo garantisce la compliance.

Tab:  ⚡ Scenari | 📈 Equity Curves | 📋 Storia
"""
from __future__ import annotations

__version__ = "9.0.0"
__all__ = ["body_t2_stress_test"]

_TICKERS   = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "GLD", "EFA"]
_SCENARIOS_LABELS = {
    "base":           ("Base (storico)", "⚪"),
    "recession":      ("Recessione",     "🔴"),
    "inflation_shock":("Shock Inflazione","🟡"),
    "credit_crisis":  ("Crisi Credito",  "🔴"),
    "goldilocks":     ("Goldilocks",      "🟢"),
}


def body_t2_stress_test(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()
    st.title("⚡ Stress Test — Scenari Forward-Looking v9.0")
    st.caption(
        "**Regola 24**: i parametri dello stress test includono scenari sintetici "
        "derivati dall'analisi macro corrente (non solo scenari storici)."
    )

    tab_scen, tab_equity, tab_hist = st.tabs(
        ["⚡ Scenari", "📈 Equity Curves", "📋 Historia"]
    )
    with tab_scen:  _render_scenarios(st, tokens)
    with tab_equity: _render_equity(st, tokens)
    with tab_hist:  _render_history(st, tokens)


def _render_scenarios(st, tokens) -> None:  # pragma: no cover
    """Configura e lancia lo stress test su tutti gli scenari."""
    st.subheader("Configura lo stress test")

    c1, c2 = st.columns(2)
    ticker  = c1.selectbox("Ticker", _TICKERS, key="t2_ticker")
    strat   = c2.selectbox("Strategia",
                            ["MA Cross (20/50)", "RSI (14)", "DSL custom"],
                            key="t2_strat")

    dsl_expr = ""
    if strat == "DSL custom":
        dsl_expr = st.text_input("Espressione DSL", "EMA(close, 20) > close",
                                 key="t2_dsl")

    c_fees, c_slip, c_cash = st.columns(3)
    fees = c_fees.number_input("Fees %", 0.01, 2.0, 0.10, 0.01, key="t2_fees") / 100
    slip = c_slip.number_input("Slippage %", 0.01, 2.0, 0.10, 0.01, key="t2_slip") / 100
    cash = c_cash.number_input("Capitale $", 1_000, 100_000, 10_000, 1_000, key="t2_cash")

    # Descrizione scenari
    with st.expander("ℹ️ Descrizione scenari"):
        st.markdown("""
| Scenario | Drift/giorno | Volatilità | Spike iniziale |
|---|---|---|---|
| 🟢 **Goldilocks** | +0.12% | −20% | No |
| ⚪ **Base** | storico | storico | No |
| 🟡 **Inflation Shock** | −0.08% | +40% | 5 giorni |
| 🔴 **Recession** | −0.20% | +60% | No |
| 🔴 **Credit Crisis** | −0.30% | +80% | 10 giorni |
        """)

    if not st.button("⚡ Esegui tutti gli scenari", key="t2_run"):
        return

    try:
        from engine.backtesting.strategy_builder import build_strategy_from_dsl
        from engine.backtesting.strategies.ma_cross import MovingAverageCrossover
        from engine.backtesting.strategies.rsi import RSIStrategy
        from engine.stress_test.forward_scenarios import StressTestRunner
        from shared.db.prices_repo import get_prices_repository
        from shared.types import TimeFrame

        strat_map = {
            "MA Cross (20/50)": MovingAverageCrossover(fast=20, slow=50),
            "RSI (14)":         RSIStrategy(period=14),
        }
        strat_obj = strat_map.get(strat) or build_strategy_from_dsl(dsl_expr)

        repo = get_prices_repository()
        df   = repo.read_ohlcv(ticker=ticker, exchange="NASDAQ",
                                timeframe=TimeFrame.D1, limit=400)
        if df is None or df.empty:
            st.error(f"Nessun dato OHLCV per **{ticker}**.")
            return

        runner = StressTestRunner(initial_cash=float(cash), fees=fees, slippage=slip)
        with st.spinner("Esecuzione 5 scenari forward-looking…"):
            results = runner.run_all_scenarios(strat_obj, df, ticker=ticker)
            compare = runner.compare_scenarios(results)

        st.session_state["t2_results"] = results
        st.session_state["t2_compare"] = compare
        st.session_state["t2_ticker"]  = ticker

        # Tabella comparativa
        st.markdown("**Tabella comparativa (ordinata per Sharpe)**")
        st.dataframe(
            compare.style.background_gradient(subset=["sharpe"], cmap="RdYlGn"),
            use_container_width=True,
        )

        # Highlight: scenario peggiore vs migliore
        if not compare.empty:
            best  = compare.iloc[0]
            worst = compare.iloc[-1]
            col_b, col_w = st.columns(2)
            col_b.success(f"🟢 Migliore: **{best['scenario']}** — Sharpe {best['sharpe']:.3f}")
            col_w.error(f"🔴 Peggiore: **{worst['scenario']}** — Sharpe {worst['sharpe']:.3f}")

    except Exception as exc:
        st.error(f"Errore stress test: {exc}")


def _render_equity(st, tokens) -> None:  # pragma: no cover
    """Mostra le equity curve sovrapposte per tutti gli scenari."""
    results = st.session_state.get("t2_results")
    if not results:
        st.info("Esegui prima lo stress test dalla tab **⚡ Scenari**.")
        return

    import plotly.graph_objects as go
    _COLS = {
        "base":           tokens.colors.neutral,
        "goldilocks":     tokens.colors.positive,
        "recession":      tokens.colors.negative,
        "inflation_shock":tokens.colors.warning,
        "credit_crisis":  "#FF6600",
    }

    fig = go.Figure()
    for scen, res in results.items():
        label = _SCENARIOS_LABELS.get(scen, (scen, "⚪"))[0]
        fig.add_scatter(
            x=list(range(len(res.equity_curve))),
            y=res.equity_curve.values,
            name=label,
            line={"color": _COLS.get(scen, tokens.colors.accent_primary), "width": 2},
        )

    fig.update_layout(
        title=f"Equity Curve per Scenario — {st.session_state.get('t2_ticker', '')}",
        height=420,
        template=tokens.plotly.template,
        paper_bgcolor=tokens.plotly.paper_bgcolor,
        plot_bgcolor=tokens.plotly.plot_bgcolor,
        font={"family": tokens.plotly.font_family, "color": tokens.plotly.font_color},
        legend={"orientation": "h"},
        margin={"l": 0, "r": 0, "t": 60, "b": 0},
        xaxis_title="Barre",
        yaxis_title="Equity ($)",
    )
    st.plotly_chart(fig, use_container_width=True)

    compare = st.session_state.get("t2_compare")
    if compare is not None and not compare.empty:
        st.subheader("Metriche per scenario")
        for _, row in compare.iterrows():
            icon = _SCENARIOS_LABELS.get(str(row["scenario"]), ("", "⚪"))[1]
            sc_c = st.columns(5)
            sc_c[0].markdown(f"{icon} **{row['scenario']}**")
            sc_c[1].metric("Sharpe",      f"{row['sharpe']:.3f}")
            sc_c[2].metric("Max DD",      f"{row['max_dd']:.1%}")
            sc_c[3].metric("Return",      f"{row['total_return']:.1%}")
            sc_c[4].metric("Trade",       str(row['n_trades']))


def _render_history(st, tokens) -> None:  # pragma: no cover
    """Mostra la storia dei run stress test da backtest_results."""
    st.subheader("📋 Storia stress test")
    try:
        from engine.backtesting.backtest_runner import BacktestRunner
        df = BacktestRunner().read_results(run_type="stress", limit=20)
        if df.empty:
            st.info("Nessun run stress salvato.")
        else:
            st.dataframe(df, use_container_width=True)
    except Exception as exc:
        st.warning(f"Storia non disponibile: {exc}")
