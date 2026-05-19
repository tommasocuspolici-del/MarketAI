# ruff: noqa: N999
"""Q6 — Technical Advanced Analysis ★ NUOVO (v1.0 — Fase 2).

Integra i quattro motori di analisi tecnica avanzata:
  1. MultiTimeframeAnalyzer — confluenza segnali D/W/M
  2. CycleAnalyzer          — Hurst exponent + ciclo FFT dominante
  3. VolumeProfileCalculator — POC, VAH, VAL, VWAP
  4. OrderFlowAnalyzer       — pressione acquisti/vendite

Regola 33: tutti i dati provengono da PricesRepo (DuckDB) o yfinance live.
Regola 34: cache @st.cache_data(ttl=900) per ogni sezione.
"""
from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["body_q6_technical_advanced"]

_DEFAULT_TICKER  = "SPY"
_WATCH_TICKERS   = ["SPY", "QQQ", "GLD", "TLT", "^VIX"]


def body_q6_technical_advanced(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    st.title("🔬 Analisi Tecnica Avanzata")
    st.caption(
        "Multi-Timeframe Confluence · Hurst Exponent · FFT Cycle · "
        "Volume Profile · Order Flow"
    )

    cols_top = st.columns([3, 1, 1])
    with cols_top[1]:
        ticker = st.selectbox("Ticker", _WATCH_TICKERS, key="q6_ticker")
    with cols_top[2]:
        if st.button("🔄 Aggiorna", key="q6_refresh"):
            st.cache_data.clear()
            st.rerun()

    # ── Caricamento dati OHLCV ─────────────────────────────────────────────
    @st.cache_data(ttl=900)
    def _load_ohlcv(sym: str):
        try:
            import yfinance as yf
            hist = yf.Ticker(sym).history(period="2y")
            if hist.empty or len(hist) < 60:
                return None
            hist.index = hist.index.tz_localize(None)
            return hist[["Open", "High", "Low", "Close", "Volume"]].rename(
                columns=str.lower
            )
        except Exception:
            return None

    df = _load_ohlcv(ticker)

    if df is None:
        st.warning(
            f"Dati OHLCV non disponibili per **{ticker}**. "
            "Verifica la connessione internet."
        )
        return

    import pandas as pd

    tab_mtf, tab_cycle, tab_volume, tab_flow = st.tabs([
        "📐 Multi-Timeframe",
        "🔄 Ciclo & Hurst",
        "📊 Volume Profile",
        "💧 Order Flow",
    ])

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1 — Multi-Timeframe Confluence
    # ══════════════════════════════════════════════════════════════════════════
    with tab_mtf:
        st.subheader("📐 Multi-Timeframe Confluence Signal (D / W / M)")
        st.caption(
            "Confluenza di tre timeframe: segnale ad alta convinzione quando "
            "tutti e tre concordano. Indicatori: SMA20/50 crossover, RSI, VWAP relativo."
        )

        @st.cache_data(ttl=900)
        def _mtf_signal(sym: str, data_hash: int):
            from engine.analytics.technical.multi_timeframe_analyzer import MultiTimeframeAnalyzer
            import yfinance as yf
            hist = yf.Ticker(sym).history(period="2y")
            if hist.empty:
                return None
            hist.index = hist.index.tz_localize(None)
            df_ = hist[["Open", "High", "Low", "Close", "Volume"]].rename(columns=str.lower)
            analyzer = MultiTimeframeAnalyzer()
            return analyzer.analyze(df_, ticker=sym)

        data_hash = hash(ticker)
        mtf = _mtf_signal(ticker, data_hash)

        if mtf is None:
            st.info("Analisi multi-timeframe non disponibile.")
        else:
            score_label = (
                "🟢 RIALZISTA" if mtf.confluence_score > 0.3 else
                "🔴 RIBASSISTA" if mtf.confluence_score < -0.3 else
                "⚪ NEUTRO"
            )
            col1, col2, col3 = st.columns(3)
            col1.metric(
                "Confluence Score",
                f"{mtf.confluence_score:+.3f}",
                score_label,
            )
            col2.metric("Convinzione", mtf.conviction)
            col3.metric("Timeframe concordanti", f"{mtf.agreeing_count}/3")

            st.divider()
            st.markdown("**Breakdown per Timeframe**")
            tf_rows = []
            for tf_sig in mtf.timeframe_signals:
                tf_rows.append({
                    "Timeframe":     tf_sig.timeframe.upper(),
                    "SMA Signal":    f"{tf_sig.sma_signal:+.2f}",
                    "RSI":           f"{tf_sig.rsi:.1f}" if tf_sig.rsi else "N/D",
                    "VWAP Signal":   f"{tf_sig.vwap_signal:+.2f}",
                    "Score finale":  f"{tf_sig.combined_score:+.3f}",
                    "Direzione":     tf_sig.direction.upper(),
                })
            st.dataframe(pd.DataFrame(tf_rows), hide_index=True, use_container_width=True)

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2 — Cycle Analyzer (Hurst + FFT)
    # ══════════════════════════════════════════════════════════════════════════
    with tab_cycle:
        st.subheader("🔄 Hurst Exponent & Ciclo Dominante FFT")
        st.caption(
            "Hurst > 0.5 → tendente (trend-following favorito) · "
            "Hurst ≈ 0.5 → random walk · "
            "Hurst < 0.5 → mean-reverting"
        )

        @st.cache_data(ttl=900)
        def _cycle_result(sym: str, data_hash: int):
            from engine.analytics.technical.cycle_analyzer import CycleAnalyzer
            import yfinance as yf
            hist = yf.Ticker(sym).history(period="2y")
            if hist.empty or len(hist) < 60:
                return None
            closes = hist["Close"].dropna().values
            analyzer = CycleAnalyzer()
            return analyzer.analyze(closes)

        cycle = _cycle_result(ticker, hash(ticker))

        if cycle is None:
            st.info("Analisi ciclo non disponibile.")
        else:
            hurst_color = (
                "🟢" if cycle.hurst_regime == "trending" else
                "🔴" if cycle.hurst_regime == "mean_reverting" else
                "🟡"
            )
            col1, col2, col3 = st.columns(3)
            col1.metric(
                "Hurst Exponent",
                f"{cycle.hurst:.3f}" if cycle.hurst is not None else "N/D",
                f"{hurst_color} {cycle.hurst_regime.replace('_', ' ').title()}",
            )
            col2.metric(
                "Ciclo Dominante",
                f"{cycle.dominant_cycle_days}d" if cycle.dominant_cycle_days else "N/D",
                help="Ciclo dominante rilevato con FFT su rendimenti de-trended.",
            )
            col3.metric("Osservazioni", str(cycle.n_obs))

            st.divider()
            st.markdown("**Cosa significa questo regime?**")
            if cycle.hurst_regime == "trending":
                st.success(
                    "📈 **Mercato tendente** — il momentum è persistente. "
                    "Strategie trend-following (breakout, SMA crossover) sono favorite."
                )
            elif cycle.hurst_regime == "mean_reverting":
                st.info(
                    "🔄 **Mercato mean-reverting** — le deviazioni dalla media vengono corrette. "
                    "Strategie mean-reversion (Bollinger Bands, RSI oversold/overbought) sono favorite."
                )
            else:
                st.warning(
                    "⚪ **Random walk** — nessuna struttura sfruttabile evidente. "
                    "Attenzione ai costi di transazione — il mercato è vicino all'efficienza."
                )

            if cycle.dominant_cycle_days:
                days = cycle.dominant_cycle_days
                if 15 <= days <= 25:
                    st.caption(f"Ciclo ~{days}d ≈ ciclo mensile (lunare)")
                elif 55 <= days <= 70:
                    st.caption(f"Ciclo ~{days}d ≈ ciclo trimestrale")
                elif 120 <= days <= 135:
                    st.caption(f"Ciclo ~{days}d ≈ ciclo semi-annuale")

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 3 — Volume Profile (VPVR)
    # ══════════════════════════════════════════════════════════════════════════
    with tab_volume:
        st.subheader("📊 Volume Profile — POC · VAH · VAL · VWAP")
        st.caption(
            "Point of Control (POC): livello di prezzo con volume massimo. "
            "Value Area: 70% del volume totale. VWAP: fair value volume-weighted."
        )

        @st.cache_data(ttl=900)
        def _volume_profile(sym: str, data_hash: int):
            from engine.analytics.technical.volume_profile import VolumeProfileCalculator
            import yfinance as yf
            hist = yf.Ticker(sym).history(period="3mo")
            if hist.empty or len(hist) < 20:
                return None
            hist.index = hist.index.tz_localize(None)
            df_ = hist[["High", "Low", "Close", "Volume"]].rename(columns=str.lower)
            calc = VolumeProfileCalculator()
            return calc.calculate(df_)

        vp = _volume_profile(ticker, hash(ticker))

        if vp is None:
            st.info("Volume Profile non disponibile.")
        else:
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("POC",  f"{vp.poc:.2f}")
            col2.metric("VAH",  f"{vp.value_area_high:.2f}")
            col3.metric("VAL",  f"{vp.value_area_low:.2f}")
            col4.metric("VWAP", f"{vp.vwap:.2f}" if vp.vwap else "N/D")

            # Segnale prezzo vs livelli chiave
            st.divider()
            st.markdown("**Segnale prezzo vs Volume Profile**")
            signal_color = (
                "🟢 Bullish" if vp.signal == "bullish" else
                "🔴 Bearish" if vp.signal == "bearish" else
                "⚪ Neutro (in value area)"
            )
            st.markdown(f"**Posizione corrente:** {signal_color}")

            if vp.signal_strength is not None:
                st.progress(
                    max(0.0, min(1.0, (vp.signal_strength + 1) / 2)),
                    text=f"Forza segnale: {vp.signal_strength:+.2f}",
                )

            st.caption(
                f"Volume profile calcolato su ultimi 3 mesi · "
                f"{vp.n_bins} bin di prezzo"
            )

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 4 — Order Flow
    # ══════════════════════════════════════════════════════════════════════════
    with tab_flow:
        st.subheader("💧 Order Flow — Pressione Acquisti/Vendite")
        st.caption(
            "Stima la pressione buy/sell tramite price action e volume. "
            "Score > 0 → prevalenza acquisti · Score < 0 → prevalenza vendite."
        )

        @st.cache_data(ttl=900)
        def _order_flow(sym: str, data_hash: int):
            from engine.analytics.technical.order_flow_analyzer import OrderFlowAnalyzer
            import yfinance as yf
            hist = yf.Ticker(sym).history(period="3mo")
            if hist.empty or len(hist) < 20:
                return None
            hist.index = hist.index.tz_localize(None)
            df_ = hist[["Open", "High", "Low", "Close", "Volume"]].rename(columns=str.lower)
            analyzer = OrderFlowAnalyzer()
            return analyzer.analyze(df_)

        of = _order_flow(ticker, hash(ticker))

        if of is None:
            st.info("Order Flow non disponibile.")
        else:
            col1, col2, col3 = st.columns(3)
            col1.metric(
                "Buy Pressure",
                f"{of.buy_pressure:.3f}" if of.buy_pressure is not None else "N/D",
            )
            col2.metric(
                "Sell Pressure",
                f"{of.sell_pressure:.3f}" if of.sell_pressure is not None else "N/D",
            )
            col3.metric(
                "Net Flow Score",
                f"{of.net_flow_score:+.3f}" if of.net_flow_score is not None else "N/D",
            )

            st.divider()
            flow_label = (
                "🟢 Prevalenza acquisti" if (of.net_flow_score or 0) > 0.1 else
                "🔴 Prevalenza vendite"  if (of.net_flow_score or 0) < -0.1 else
                "⚪ Flusso bilanciato"
            )
            st.markdown(f"**Interpretazione:** {flow_label}")

            if of.cumulative_delta is not None:
                st.metric(
                    "Cumulative Delta",
                    f"{of.cumulative_delta:+,.0f}",
                    help="Delta cumulativo: sum(volume_buy) - sum(volume_sell) nel periodo.",
                )

            st.caption(
                "Order flow stimato da price action (up-bar = buy pressure, "
                "down-bar = sell pressure, ponderato per volume)"
            )
