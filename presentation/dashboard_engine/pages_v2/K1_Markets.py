"""K1_Markets — Market Overview v9.0 (Roadmap v3.0 Settimana 8).

Pagina principale del dashboard market engine.
Integra: CompositeSignalV3 gauge, pattern signals attivi, surprise signal,
indicatori DSL personalizzati, KPI mercati.

Struttura tab:
  🎯 Segnale   — gauge CompositeV3 + breakdown + regime
  ⚡ Attivi    — pattern attivi + surprise signal
  🔧 DSL       — multi-chart indicatori personalizzati
  📈 Mercati   — KPI grid prezzi principali

REGOLA 20: zero valori hardcoded — tutti da DESIGN_TOKENS.
REGOLA 32: richiede autenticazione Streamlit (require_auth).
"""
from __future__ import annotations

from presentation.ui.cache_policy import CACHE_TTL

__version__ = "9.0.0"
__all__ = ["body_k1_markets"]


def body_k1_markets(st, tokens) -> None:  # pragma: no cover
    """Entry point della pagina K1_Markets."""
    from presentation.ui.auth import require_auth
    require_auth()
    st.title("📊 Market Overview — v9.0")

    tab_sig, tab_active, tab_dsl, tab_kpi = st.tabs([
        "🎯 Segnale", "⚡ Attivi", "🔧 DSL", "📈 Mercati",
    ])
    with tab_sig:
        _render_composite_v3(st, tokens)
    with tab_active:
        _render_active_signals(st, tokens)
    with tab_dsl:
        _render_dsl_multi_chart(st, tokens)
    with tab_kpi:
        _render_kpi_grid(st, tokens)


# ─── Tab 1: Composite Signal V3 ───────────────────────────────────────────────

def _render_composite_v3(st, tokens) -> None:  # pragma: no cover
    """Gauge CompositeSignalV3 + breakdown componenti + regime badge."""
    from presentation.ui.components.composite_gauge import render_composite_gauge
    from presentation.ui.components.regime_composite_badge import render_regime_composite_badge

    st.subheader("🔬 Composite Signal v3")

    try:
        from shared.db.duckdb_client import get_duckdb_client
        from engine.analytics.composite_signal_v3 import CompositeSignalAggregatorV3

        @st.cache_data(ttl=CACHE_TTL.PORTFOLIO_TOTALS, show_spinner=False)  # type: ignore[misc]
        def _compute():
            db = get_duckdb_client()
            return CompositeSignalAggregatorV3(duckdb=db).compute()

        out = _compute()

        import json
        breakdown = json.loads(out.breakdown_json_v3) if out.breakdown_json_v3 else {}

        render_composite_gauge(
            st=st,
            score=out.composite_score_v3,
            tokens=tokens,
            action=out.recommended_action_v3,
            confidence=out.confidence_v3,
            breakdown=breakdown,
            title="Composite Signal v3",
        )

        # Regime badge sotto il gauge
        render_regime_composite_badge(
            st,
            regime=out.v2_output.regime,
            credit_stress=out.v2_output.credit_stress,
            claims_regime=out.v2_output.claims_regime,
            vix_action=None,
        )

        # Dettaglio pattern component
        if out.pattern_count > 0:
            st.caption(
                f"🔺 Pattern component: {out.pattern_component:+.3f} "
                f"({out.pattern_count} pattern attivi)"
            )

        # Delta rispetto a v2
        delta = out.composite_score_v3 - out.v2_output.composite_score
        direction = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        st.caption(
            f"Δ rispetto a v2: {direction} {delta:+.4f} "
            f"(pattern aggiunge {out.pattern_component * 0.05:+.4f} al composite)"
        )

    except Exception as exc:
        st.warning(
            f"⚠️ CompositeSignalV3 non disponibile: {exc}\n\n"
            "Verifica che il job `analysis_pipeline` dello scheduler sia stato eseguito."
        )


# ─── Tab 2: Segnali Attivi ────────────────────────────────────────────────────

def _render_active_signals(st, tokens) -> None:  # pragma: no cover
    """Pattern signals attivi + surprise signal corrente."""
    st.subheader("⚡ Segnali Attivi")

    # ── Pattern Signals ───────────────────────────────────────────────────────
    st.markdown("**Pattern tecnici attivi (ultimi 7 giorni)**")
    try:
        from engine.technical.pattern_signals_repo import get_pattern_signals_repo
        from presentation.ui.components.pattern_overlay import build_pattern_badge_html

        repo = get_pattern_signals_repo()

        @st.cache_data(ttl=CACHE_TTL.PORTFOLIO_TOTALS, show_spinner=False)  # type: ignore[misc]
        def _active_patterns():
            return repo.read_by_type(pattern_type="", limit=20)

        df_pat = _active_patterns()
        if not df_pat.empty:
            # Filtra solo ACTIVE negli ultimi 7 giorni (già fatto dalla query)
            for _, row in df_pat.head(10).iterrows():
                sig_icon = (
                    "🟢" if row.get("signal_dir") == "bullish"
                    else "🔴" if row.get("signal_dir") == "bearish"
                    else "⚪"
                )
                conf_pct = f"{float(row.get('confidence', 0)):.0%}"
                st.markdown(
                    f"{sig_icon} **{row.get('ticker', '?')}** — "
                    f"{str(row.get('pattern_type', '')).replace('_', ' ').title()} "
                    f"· confidence {conf_pct}",
                )
        else:
            st.info("Nessun pattern attivo nelle ultime 7 giorni.")

    except Exception as exc:
        st.caption(f"Pattern signals: {exc}")

    st.divider()

    # ── Economic Surprise Signal ──────────────────────────────────────────────
    st.markdown("**Economic Surprise Signal**")
    try:
        from shared.db.duckdb_client import get_duckdb_client

        @st.cache_data(ttl=CACHE_TTL.BACKTESTING, show_spinner=False)  # type: ignore[misc]
        def _surprise_signal():
            db = get_duckdb_client()
            rows = db.query(
                "SELECT signal_value, dominant_sector, beat_count, miss_count, generated_at "
                "FROM surprise_signal ORDER BY generated_at DESC LIMIT 1"
            )
            return rows[0] if rows else None

        row = _surprise_signal()
        if row:
            val, sector, beats, misses, gen_at = row
            color = tokens.colors.positive if float(val) > 0.1 else (
                tokens.colors.negative if float(val) < -0.1 else tokens.colors.warning
            )
            icon  = "🟢" if float(val) > 0.1 else ("🔴" if float(val) < -0.1 else "⚪")
            c1, c2, c3 = st.columns(3)
            c1.metric("Surprise Signal", f"{float(val):+.4f}")
            c2.metric("Settore dominante", str(sector or "—"))
            c3.metric("Beat / Miss", f"{beats} / {misses}")
            st.caption(f"Aggiornato: {gen_at}")
        else:
            st.info("Surprise signal non disponibile — esegui il job `surprise_engine_v2`.")

    except Exception as exc:
        st.caption(f"Surprise signal: {exc}")


# ─── Tab 3: Multi-chart DSL ───────────────────────────────────────────────────

def _render_dsl_multi_chart(st, tokens) -> None:  # pragma: no cover
    """Grafico multi-indicatore DSL dall'IndicatorRegistry."""
    st.subheader("🔧 Indicatori DSL personalizzati")

    ticker = st.selectbox("Ticker", ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"],
                          key="k1_dsl_ticker")
    try:
        from shared.db.prices_repo import get_prices_repository
        from shared.types import TimeFrame
        from engine.technical.indicator_registry import get_indicator_registry

        @st.cache_data(ttl=CACHE_TTL.PORTFOLIO_TOTALS, show_spinner=False)  # type: ignore[misc]
        def _ohlcv(t: str):
            return get_prices_repository().read_ohlcv(
                ticker=t, exchange="NASDAQ", timeframe=TimeFrame.D1, limit=200
            )

        df = _ohlcv(ticker)
        if df is None or df.empty:
            st.info(f"Nessun dato OHLCV per **{ticker}**. Avvia lo scheduler.")
            return

        registry = get_indicator_registry()
        results  = registry.evaluate_all(df, ticker)

        if not results:
            st.info(
                "Nessun indicatore DSL salvato. "
                "Aggiungi indicatori nella pagina K2 Equity → tab 🔧 Indicatori."
            )
            return

        import plotly.graph_objects as go

        fig = go.Figure()
        # Aggiunge la Close come riferimento
        fig.add_scatter(
            x=df["ts"], y=df["close"],
            name="Close", mode="lines",
            line={"color": tokens.colors.accent_primary, "width": 1.5, "dash": "dot"},
            yaxis="y",
        )

        # Aggiunge ogni indicatore DSL su assi secondari
        y_axes: dict[str, int] = {}
        for i, (ind_name, series) in enumerate(list(results.items())[:5]):
            y_key = f"y{i + 2}" if i > 0 else "y2"
            y_axes[ind_name] = i + 2
            fig.add_scatter(
                x=df["ts"], y=series,
                name=ind_name, mode="lines",
                yaxis=y_key,
            )

        # Layout multi-asse
        fig.update_layout(
            template=tokens.plotly.template,
            paper_bgcolor=tokens.plotly.paper_bgcolor,
            plot_bgcolor=tokens.plotly.plot_bgcolor,
            font={"family": tokens.plotly.font_family, "color": tokens.plotly.font_color},
            height=380,
            margin={"l": 0, "r": 0, "t": 30, "b": 0},
            legend={"orientation": "h"},
            yaxis={"title": "Close", "showgrid": True},
            yaxis2={"overlaying": "y", "side": "right", "showgrid": False},
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"{len(results)} indicatori attivi per {ticker}")

    except Exception as exc:
        st.warning(f"Errore indicatori DSL: {exc}")


# ─── Tab 4: KPI Mercati ───────────────────────────────────────────────────────

def _render_kpi_grid(st, tokens) -> None:  # pragma: no cover
    """Griglia KPI prezzi mercati principali (6 ticker)."""
    st.subheader("📈 KPI Mercati")

    kpi_tickers = [
        ("S&P 500",  "SPY"),  ("NASDAQ",   "QQQ"),
        ("Gold",     "GLD"),  ("WTI Oil",  "USO"),
        ("EUR/USD",  "EURUSD=X"), ("VIX",  "^VIX"),
    ]

    try:
        from shared.db.prices_repo import get_prices_repository
        from shared.types import TimeFrame

        repo = get_prices_repository()
        cols = st.columns(len(kpi_tickers))

        for col, (label, ticker) in zip(cols, kpi_tickers):
            try:
                @st.cache_data(ttl=CACHE_TTL.ALERT_HISTORY, show_spinner=False)  # type: ignore[misc]
                def _px(t=ticker):
                    return repo.read_prices(ticker=t, timeframe=TimeFrame.D1)

                df = _px()
                if df is not None and len(df) >= 2:
                    close = float(df["close"].iloc[-1])
                    prev  = float(df["close"].iloc[-2])
                    delta = (close - prev) / max(abs(prev), 1e-9) * 100
                    col.metric(label, f"{close:.2f}", f"{delta:+.2f}%")
                else:
                    col.metric(label, "N/D")
            except Exception:
                col.metric(label, "N/D")

    except Exception as exc:
        st.warning(f"Prezzi non disponibili: {exc}")
