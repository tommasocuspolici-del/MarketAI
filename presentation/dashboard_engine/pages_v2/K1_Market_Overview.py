# ruff: noqa: N999
"""K1 — Market Overview ★ aggiornato v8.3 (Composite Signal v2 breakdown).

Sezioni:
  1. Composite Signal v2 — 7 componenti pesati con gauge e breakdown
  2. KPI Mercati         — S&P500, NASDAQ, Gold, Oil, EUR/USD, VIX
  3. Regime Badge        — regime attuale + credit stress
"""
from __future__ import annotations

__version__ = "8.3.0"
__all__ = ["body_k1_market_overview"]

# Composite v2: 7 componenti con pesi base
_COMPOSITE_COMPONENTS = [
    ("technical",  "📐 Technical",   0.15),
    ("macro",      "🌐 Macro",        0.20),
    ("labour",     "👷 Labour",       0.15),
    ("sentiment",  "😊 Sentiment",    0.10),
    ("valuation",  "💰 Valuation",    0.15),
    ("surprise",   "⚡ Surprise",     0.10),
    ("volatility", "📉 Volatility",   0.15),
]


def body_k1_market_overview(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    st.title("📊 Mercati — Market Overview")
    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="k1mo_refresh"):
            st.cache_data.clear()
            st.rerun()

    # ── 1. Composite Signal v2 ─────────────────────────────────────────────
    st.subheader("🔬 Composite Signal v2 — 7 Componenti")
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()

        rows = db.query(
            "SELECT signal_date, composite_score, technical_score, macro_score, "
            "labour_score, sentiment_score, valuation_score, surprise_score, "
            "volatility_score, regime "
            "FROM composite_signal_v2 ORDER BY signal_date DESC LIMIT 1"
        )

        if not rows:
            # Fallback: old composite signal
            try:
                from shared.db.macro_repo import get_macro_repository
                from presentation.ui.components.engine_signal_summary import render_engine_signal_summary
                repo = get_macro_repository()
                composite = repo.read_composite_signal()
                render_engine_signal_summary(st, composite)
            except Exception:
                st.info("Composite Signal v2 non disponibile. Eseguire CompositeSignalAggregator.")
        else:
            r = rows[0]
            composite_score = r[1]
            scores = {
                "technical":  r[2],
                "macro":      r[3],
                "labour":     r[4],
                "sentiment":  r[5],
                "valuation":  r[6],
                "surprise":   r[7],
                "volatility": r[8],
            }
            regime = r[9] or "unknown"

            # Score gauge
            score_label = (
                "🟢 RIALZISTA" if composite_score > 0.3 else
                "🔴 RIBASSISTA" if composite_score < -0.3 else
                "🟡 NEUTRO"
            )
            col_gauge, col_regime = st.columns([2, 1])
            with col_gauge:
                st.metric(
                    "Composite Signal v2",
                    f"{composite_score:+.3f}" if composite_score is not None else "N/A",
                    delta=score_label,
                )
            with col_regime:
                st.metric("Regime", regime.upper())

            st.caption(f"Data: {r[0]}")
            st.divider()

            # 7-component breakdown
            st.markdown("**Breakdown Componenti**")
            for key, label, weight in _COMPOSITE_COMPONENTS:
                score = scores.get(key)
                if score is None:
                    st.progress(0.5, text=f"{label} (peso {weight:.0%}) — N/A")
                    continue

                # Map [-1,+1] → [0,1] for progress bar
                bar_val = max(0.0, min(1.0, (score + 1.0) / 2.0))
                color_txt = (
                    "🟢" if score > 0.2 else "🔴" if score < -0.2 else "🟡"
                )
                st.progress(
                    bar_val,
                    text=f"{color_txt} {label} (peso {weight:.0%})  →  {score:+.3f}",
                )

    except Exception as exc:
        st.warning(f"Composite Signal non disponibile: {exc}")

    st.divider()

    # ── 2. KPI Mercati ────────────────────────────────────────────────────
    st.subheader("📈 KPI Mercati")
    kpi_tickers = [
        ("S&P 500", "SPY"), ("NASDAQ", "QQQ"), ("Gold", "GLD"),
        ("WTI Oil", "USO"), ("EUR/USD", "EURUSD=X"), ("VIX", "^VIX"),
    ]
    try:
        from shared.db.prices_repo import get_prices_repository
        from shared.types import TimeFrame
        repo_p = get_prices_repository()
        cols = st.columns(len(kpi_tickers))
        for col, (label, ticker) in zip(cols, kpi_tickers):
            try:
                df = repo_p.read_prices(ticker=ticker, timeframe=TimeFrame.D1)
                if df is not None and not df.empty and len(df) >= 2:
                    close = float(df["close"].iloc[-1])
                    prev  = float(df["close"].iloc[-2])
                    delta = (close - prev) / prev * 100
                    col.metric(label, f"{close:.2f}", f"{delta:+.2f}%")
                else:
                    col.metric(label, "N/D")
            except Exception:
                col.metric(label, "N/D")
    except Exception as exc:
        st.warning(f"Prezzi non disponibili: {exc}")

    st.divider()

    # ── 3. Composite Signal Trend ─────────────────────────────────────────
    st.subheader("📅 Trend Composite — Ultime 30 Rilevazioni")
    try:
        from shared.db.duckdb_client import get_duckdb_client
        import pandas as pd
        db = get_duckdb_client()
        hist = db.query(
            "SELECT signal_date, composite_score FROM composite_signal_v2 "
            "ORDER BY signal_date DESC LIMIT 30"
        )
        if hist and len(hist) >= 4:
            df_t = pd.DataFrame(hist, columns=["Data", "Composite"])
            df_t = df_t.sort_values("Data").set_index("Data")
            st.line_chart(df_t, height=200)
            st.caption("Composite Score [-1,+1] — cambio segno = alert regime shift")
    except Exception:
        pass  # Silenzioso se non disponibile (sezione secondaria)

    # ── 4. Regime Badge ───────────────────────────────────────────────────
    try:
        from presentation.ui.components.regime_composite_badge import render_regime_composite_badge
        from shared.db.macro_repo import get_macro_repository
        repo = get_macro_repository()
        composite = repo.read_composite_signal()
        if composite:
            render_regime_composite_badge(
                st,
                regime=composite.regime,
                credit_stress=composite.credit_stress,
                claims_regime=composite.claims_regime,
                vix_action=None,
            )
    except Exception:
        pass
