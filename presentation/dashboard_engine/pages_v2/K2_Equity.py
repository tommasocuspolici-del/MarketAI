# ruff: noqa: N999
"""K2 — Equity (v9.0). Aggiunge tab Fondamentali, Bilancio e Score.

Roadmap v3.0 Settimana 2: integrazione FundamentalsAnalyzer.

Tab disponibili:
  📈 Grafico    — candlestick OHLCV + KPI prezzo
  📋 Fondamentali — P/E, P/B, EV/EBITDA, dividend yield, beta
  📊 Bilancio   — revenue, net income, FCF trend (4 quarter)
  🎯 Score      — quality/value/growth score con gauge

Regola 20: zero colori hardcoded — tutti da DESIGN_TOKENS.
"""
from __future__ import annotations

from presentation.ui.cache_policy import CACHE_TTL

try:
    import pandas as pd
except ImportError:
    pass

__version__ = "9.0.0"
__all__ = ["body_k2_equity"]

_DEFAULT_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "NVDA", "AMZN",
    "META", "TSLA", "JPM", "SPY", "QQQ",
]

_TICKER_SECTOR: dict[str, str] = {
    "AAPL": "Technology", "MSFT": "Technology",
    "GOOGL": "Communication Services", "META": "Communication Services",
    "NVDA": "Technology", "AMZN": "Consumer Discretionary",
    "TSLA": "Consumer Discretionary", "JPM": "Financials",
    "SPY": "Unknown", "QQQ": "Unknown",
}


def _is_nan(v: object) -> bool:
    try:
        import math
        return math.isnan(float(v))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return True


def _fmt_ratio(v: object, decimals: int = 1) -> str:
    if v is None or _is_nan(v):
        return "N/D"
    return f"{float(v):.{decimals}f}x"  # type: ignore[arg-type]


def _fmt_pct(v: object) -> str:
    if v is None or _is_nan(v):
        return "N/D"
    return f"{float(v)*100:.2f}%"  # type: ignore[arg-type]


def _fmt_billions(v: object) -> str:
    if v is None or _is_nan(v):
        return "N/D"
    return f"${float(v)/1e9:.1f}B"  # type: ignore[arg-type]


def _fmt_score(v: object, with_sign: bool = False) -> str:
    if v is None or _is_nan(v):
        return "N/D"
    fmt = f"{float(v):+.2f}" if with_sign else f"{float(v):.2f}"  # type: ignore[arg-type]
    return fmt


def body_k2_equity(st, tokens) -> None:  # pragma: no cover
    """Render K2 Equity page with price chart + fundamentals tabs."""
    from presentation.ui.auth import require_auth
    require_auth()
    st.title("📊 Mercati — Equity")
    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="k2_refresh"):
            st.cache_data.clear()
            st.rerun()

    ticker: str = st.selectbox("Ticker", _DEFAULT_TICKERS, key="k2_ticker")
    sector: str = _TICKER_SECTOR.get(ticker, "Unknown")

    tab_chart, tab_fund, tab_balance, tab_score, tab_ind = st.tabs([
        "📈 Grafico", "📋 Fondamentali", "📊 Bilancio", "🎯 Score", "🔧 Indicatori"
    ])

    with tab_chart:
        _render_chart(st, tokens, ticker)
    with tab_fund:
        _render_fundamentals(st, tokens, ticker)
    with tab_balance:
        _render_balance(st, tokens, ticker)
    with tab_score:
        _render_score(st, tokens, ticker, sector)
    with tab_ind:
        _render_indicators(st, tokens, ticker)


def _render_chart(st, tokens, ticker: str) -> None:  # pragma: no cover
    try:
        import plotly.graph_objects as go
        from shared.db.prices_repo import get_prices_repository
        from shared.types import TimeFrame

        @st.cache_data(ttl=CACHE_TTL.PORTFOLIO_TOTALS, show_spinner=False)
        def _fetch(t: str):
            return get_prices_repository().read_prices(ticker=t, timeframe=TimeFrame.D1)

        df = _fetch(ticker)
        if df is None or df.empty:
            st.info(f"Nessun dato OHLCV per **{ticker}**. Avvia lo scheduler.")
            return

        df = df.tail(252)
        fig = go.Figure(data=[go.Candlestick(
            x=df["ts"], open=df["open"], high=df["high"],
            low=df["low"], close=df["close"], name=ticker,
            increasing_line_color=tokens.colors.accent,
            decreasing_line_color=tokens.colors.semantic_negative,
        )])
        fig.update_layout(
            height=380, title=f"{ticker} — ultimi 252 giorni",
            margin=dict(l=0, r=0, t=40, b=0),
            xaxis_rangeslider_visible=False,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color=tokens.colors.text_primary,
        )
        st.plotly_chart(fig, use_container_width=True)
        close = float(df["close"].iloc[-1])
        prev  = float(df["close"].iloc[-2])
        delta = (close - prev) / prev * 100
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Prezzo", f"{close:.2f}", f"{delta:+.2f}%")
        c2.metric("Max 52W", f"{float(df['high'].max()):.2f}")
        c3.metric("Min 52W", f"{float(df['low'].min()):.2f}")
        c4.metric("Vol medio", f"{float(df['volume'].mean())/1e6:.1f}M")
    except Exception as exc:
        st.warning(f"Grafico non disponibile: {exc}")


def _render_fundamentals(st, tokens, ticker: str) -> None:  # pragma: no cover
    try:
        from shared.db.fundamentals_repo import get_fundamentals_repository

        @st.cache_data(ttl=CACHE_TTL.MACRO_CONVICTION, show_spinner=False)
        def _fetch(t: str):
            return get_fundamentals_repository().read_latest_valuation(t)

        val = _fetch(ticker)
        if val is None:
            st.info(
                f"Nessun dato valutativo per **{ticker}**.\n"
                "Lo scheduler `av_fundamentals` aggiornerà i dati lunedì 07:30 UTC."
            )
            return
        st.subheader(f"📋 Multipli — {ticker}")
        c1, c2, c3 = st.columns(3)
        c1.metric("P/E TTM",    _fmt_ratio(val.get("pe_ttm")))
        c2.metric("P/E Forward", _fmt_ratio(val.get("pe_forward")))
        c3.metric("P/Book",     _fmt_ratio(val.get("pb")))
        c4, c5, c6 = st.columns(3)
        c4.metric("EV/EBITDA",      _fmt_ratio(val.get("ev_ebitda")))
        c5.metric("Dividend Yield", _fmt_pct(val.get("dividend_yield")))
        c6.metric("Beta",           _fmt_ratio(val.get("beta"), decimals=2))
        c7, c8 = st.columns(2)
        c7.metric("P/Sales", _fmt_ratio(val.get("ps")))
        mc = val.get("market_cap")
        c8.metric("Market Cap", _fmt_billions(mc) if mc else "N/D")
        fetched = val.get("computed_at")
        if fetched:
            import pandas as _pd
            st.caption(f"🕐 {_pd.Timestamp(fetched).strftime('%Y-%m-%d %H:%M UTC')}")
    except Exception as exc:
        st.warning(f"Dati fondamentali non disponibili: {exc}")


def _render_balance(st, tokens, ticker: str) -> None:  # pragma: no cover
    try:
        import pandas as _pd
        import plotly.graph_objects as go
        from shared.db.fundamentals_repo import get_fundamentals_repository

        @st.cache_data(ttl=CACHE_TTL.MACRO_CONVICTION, show_spinner=False)
        def _fi(t): return get_fundamentals_repository().read_income(t, limit=8)
        @st.cache_data(ttl=CACHE_TTL.MACRO_CONVICTION, show_spinner=False)
        def _fb(t): return get_fundamentals_repository().read_balance_sheet(t, limit=8)

        inc = _fi(ticker)
        bal = _fb(ticker)
        if inc.empty:
            st.info(f"Nessun dato bilancio per **{ticker}**. Avvia `edgar_fundamentals`.")
            return

        st.subheader(f"📊 Bilancio — {ticker}")
        scale = 1e9

        def _lbl(r):
            try:
                d = _pd.Timestamp(r["report_date"]).strftime("%Y")
                p = r.get("period", "")
                return f"{d}-{p}" if p else d
            except Exception:
                return "?"

        inc["lbl"] = inc.apply(_lbl, axis=1)
        labels = inc["lbl"].tolist()[::-1]

        fig = go.Figure()
        for col, name, color in [
            ("revenue",    "Ricavi",       tokens.colors.accent),
            ("net_income", "Utile Netto",  tokens.colors.semantic_positive),
        ]:
            vals = inc[col].fillna(0).values[::-1] / scale
            fig.add_bar(x=labels, y=vals, name=name, marker_color=color)

        if not bal.empty and "fcf" in bal.columns:
            n = min(len(labels), len(bal))
            fcf_vals = bal["fcf"].fillna(0).values[::-1] / scale
            fig.add_trace(go.Scatter(
                x=labels[:n], y=fcf_vals[:n], name="FCF",
                mode="lines+markers",
                line=dict(color=tokens.colors.semantic_warning, width=2),
                yaxis="y2",
            ))

        fig.update_layout(
            barmode="group", height=340,
            margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color=tokens.colors.text_primary,
            legend=dict(orientation="h"),
            yaxis=dict(title="Miliardi USD"),
            yaxis2=dict(title="FCF (Mld)", overlaying="y", side="right"),
        )
        st.plotly_chart(fig, use_container_width=True)
        last = inc.iloc[0]
        c1, c2, c3 = st.columns(3)
        c1.metric("Ricavi", _fmt_billions(last.get("revenue")))
        c2.metric("Utile Netto", _fmt_billions(last.get("net_income")))
        c3.metric("EPS Diluito", _fmt_ratio(last.get("eps_diluted"), decimals=2))
    except Exception as exc:
        st.warning(f"Dati bilancio non disponibili: {exc}")


def _render_score(st, tokens, ticker: str, sector: str) -> None:  # pragma: no cover
    try:
        import plotly.graph_objects as go
        from engine.fundamentals.fundamentals_analyzer import FundamentalsAnalyzer

        @st.cache_data(ttl=CACHE_TTL.FOREX_COMMODITY, show_spinner=True)
        def _compute(t: str, s: str):
            return FundamentalsAnalyzer().compute(t, sector=s)

        score = _compute(ticker, sector)
        if score is None:
            st.info(
                f"Score non calcolabile per **{ticker}**: fondamentali assenti.\n"
                "Avvia `edgar_fundamentals` e `av_fundamentals`."
            )
            return

        st.subheader(f"🎯 Fundamental Score — {ticker}")
        comp = score.composite_score
        comp_str = f"{comp:+.2f}" if comp is not None else "N/D"
        st.markdown(f"### {score.signal_icon} **{score.signal}** — Composite: `{comp_str}`")
        st.caption(f"Settore: {sector} · Periodi usati: {score.data_periods_used}")

        if comp is not None:
            fig = go.Figure(go.Indicator(
                mode="gauge+number",
                value=float(comp),
                gauge={
                    "axis": {"range": [-1, 1]},
                    "bar": {"color": tokens.colors.accent},
                    "bgcolor": "rgba(0,0,0,0)",
                    "steps": [
                        {"range": [-1, -0.3], "color": tokens.colors.semantic_negative},
                        {"range": [-0.3, 0.3], "color": tokens.colors.semantic_warning},
                        {"range": [0.3, 1],   "color": tokens.colors.semantic_positive},
                    ],
                },
                domain={"x": [0.1, 0.9], "y": [0, 1]},
            ))
            fig.update_layout(
                height=220, margin=dict(l=10, r=10, t=10, b=10),
                paper_bgcolor="rgba(0,0,0,0)",
                font={"color": tokens.colors.text_primary},
            )
            st.plotly_chart(fig, use_container_width=True)

        c1, c2, c3 = st.columns(3)
        c1.metric("🏗 Quality",  _fmt_score(score.quality_score),
                  help="[0=basso, 1=alto] Margini, FCF, leva")
        c2.metric("💰 Value",   _fmt_score(score.value_score, with_sign=True),
                  help="+1=molto economico vs settore, -1=molto caro")
        c3.metric("📈 Growth",  _fmt_score(score.growth_score, with_sign=True),
                  help="+1=forte crescita YoY, -1=contrazione")

        if score.breakdown:
            with st.expander("📐 Dettaglio componenti"):
                import json as _json
                for k, v in score.breakdown.items():
                    if v:
                        st.write(f"**{k.replace('_', ' ').title()}**")
                        st.json(v)
    except Exception as exc:
        st.warning(f"Score non disponibile: {exc}")


def _render_indicators(st, tokens, ticker: str) -> None:  # pragma: no cover
    """Tab 'Indicatori' — DSL personalizzati. ANTI-REGRESSIONE: non usare eval(),
    solo DSLEvaluator.evaluate(). validate_expression() obbligatorio prima del save.
    """
    try:
        import plotly.graph_objects as go
        from shared.db.prices_repo import get_prices_repository
        from shared.types import TimeFrame
        from engine.technical.indicator_dsl import DSLEvaluator, list_supported_functions
        from engine.technical.indicator_registry import get_indicator_registry

        registry = get_indicator_registry()

        st.subheader("➕ Nuovo indicatore")
        st.caption(
            f"Funzioni: `{'`, `'.join(list_supported_functions())}`\n\n"
            "**Esempi:** `EMA(close, 20)` · `RSI(close, 14) > 70` · "
            "`close / EMA(close, 200) - 1`"
        )

        col_name, col_expr = st.columns([1, 2])
        ind_name = col_name.text_input("Nome", placeholder="Es. RSI Signal", key="k2_ind_name")
        ind_expr = col_expr.text_input("Espressione DSL", placeholder="RSI(close, 14)", key="k2_ind_expr")
        ind_desc = st.text_input("Descrizione (opzionale)", key="k2_ind_desc")
        c1, c2, c3 = st.columns(3)
        chart_type  = c1.selectbox("Chart", ["line", "bar", "area"], key="k2_ind_ct")
        overlay     = c2.checkbox("Sovrapponi", key="k2_ind_ov")
        ticker_only = c3.checkbox(f"Solo {ticker}", key="k2_ind_tf")

        if st.button("💾 Salva", key="k2_ind_save"):
            if not ind_name.strip() or not ind_expr.strip():
                st.error("Nome ed espressione sono obbligatori.")
            else:
                try:
                    registry.save(
                        name=ind_name.strip(), expression=ind_expr.strip(),
                        description=ind_desc, chart_type=chart_type, overlay=overlay,
                        ticker_filter=ticker if ticker_only else None,
                    )
                    st.success(f"✅ **{ind_name}** salvato.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"❌ {exc}")

        # Preview live prima del salvataggio
        if ind_expr.strip():
            try:
                @st.cache_data(ttl=CACHE_TTL.PORTFOLIO_TOTALS, show_spinner=False)
                def _ohlcv(t):
                    return get_prices_repository().read_ohlcv(
                        ticker=t, exchange="NASDAQ", timeframe=TimeFrame.D1, limit=120
                    )
                df_p = _ohlcv(ticker)
                if df_p is not None and not df_p.empty:
                    series = DSLEvaluator().evaluate(ind_expr.strip(), df_p)
                    fig_p  = go.Figure()
                    fig_p.add_scatter(x=df_p["ts"], y=series, mode="lines",
                                      line=dict(color=tokens.colors.accent, width=1.5))
                    fig_p.update_layout(
                        title=f"Preview: {ind_expr}", height=180,
                        margin=dict(l=0, r=0, t=28, b=0),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        font_color=tokens.colors.text_primary,
                    )
                    st.plotly_chart(fig_p, use_container_width=True)
            except Exception as exc:
                st.caption(f"Preview: {exc}")

        st.divider()
        indicators = registry.list_active(ticker)
        st.subheader(f"📋 Indicatori attivi ({len(indicators)})")
        if not indicators:
            st.info("Nessun indicatore salvato. Creane uno sopra.")
            return
        for ind in indicators:
            with st.expander(f"**{ind.name}** — `{ind.expression}`"):
                if ind.description:
                    st.caption(ind.description)
                st.code(ind.expression, language="python")
                st.caption(
                    f"{'📌 ' + ind.ticker_filter if ind.ticker_filter else '🌐 Tutti'} · "
                    f"{ind.chart_type} · overlay={ind.overlay}"
                )
                if st.button(f"🗑 Elimina", key=f"del_{ind.indicator_id}"):
                    registry.delete(ind.indicator_id)
                    st.rerun()

    except Exception as exc:
        st.warning(f"Indicatori non disponibili: {exc}")
