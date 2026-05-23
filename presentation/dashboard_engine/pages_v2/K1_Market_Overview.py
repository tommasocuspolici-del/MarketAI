# ruff: noqa: N999
"""K1 — Market Overview ★ aggiornato v8.4 (Composite Signal 9-componenti reali).

Sezioni:
  1. Composite Signal — 9 componenti reali da engine_composite_signal
  2. KPI Mercati      — S&P500, NASDAQ, Gold, Oil, EUR/USD, VIX
  3. Regime Badge     — regime attuale + credit stress
"""
from __future__ import annotations

__version__ = "8.4.0"
__all__ = ["body_k1_market_overview"]

# 9 componenti reali da _WEIGHTS in composite_signal_aggregator.py
_COMPOSITE_COMPONENTS = [
    ("vix",           "📉 VIX",         0.18),
    ("macro",         "🌐 Macro",        0.17),
    ("yield_curve",   "📈 Yield Curve",  0.15),
    ("credit",        "💳 Credit",       0.11),
    ("labour_market", "👷 Labour",       0.10),
    ("valuation",     "💰 Valuation",    0.12),
    ("claims",        "📋 Claims",       0.07),
    ("surprise",      "⚡ Surprise",     0.05),
    ("correlation",   "🔗 Correlation",  0.05),
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

    # ── 1. Composite Signal — 9 Componenti reali ──────────────────────────
    st.subheader("🔬 Composite Signal — 9 Componenti")
    try:
        import json
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()

        rows = db.query(
            "SELECT computed_at, composite_score, recommended_action, confidence, "
            "regime, component_breakdown_json "
            "FROM engine_composite_signal ORDER BY computed_at DESC LIMIT 1"
        )

        if not rows:
            st.info("Composite Signal non disponibile. Avviare lo scheduler per calcolare.")
        else:
            r = rows[0]
            computed_at      = r[0]
            composite_score  = float(r[1]) if r[1] is not None else 0.0
            action           = str(r[2]) if r[2] else "HOLD"
            confidence       = str(r[3]) if r[3] else "LOW"
            regime           = str(r[4]) if r[4] else "unknown"
            scores: dict[str, float] = json.loads(r[5]) if r[5] else {}

            score_label = (
                "🟢 RIALZISTA" if composite_score > 0.3 else
                "🔴 RIBASSISTA" if composite_score < -0.3 else
                "🟡 NEUTRO"
            )
            col_gauge, col_action, col_regime, col_conf = st.columns(4)
            with col_gauge:
                st.metric("Composite Score", f"{composite_score:+.3f}", delta=score_label)
            with col_action:
                st.metric("Azione", action)
            with col_regime:
                st.metric("Regime", regime.upper())
            with col_conf:
                st.metric("Confidence", confidence)

            st.caption(f"Calcolato: {computed_at}")
            st.divider()

            # 9-component breakdown da component_breakdown_json
            st.markdown("**Breakdown 9 Componenti**")
            for key, label, weight in _COMPOSITE_COMPONENTS:
                score = scores.get(key)
                if score is None:
                    st.progress(0.5, text=f"{label} (peso {weight:.0%}) — non calcolato")
                    continue
                bar_val = max(0.0, min(1.0, (score + 1.0) / 2.0))
                color_txt = "🟢" if score > 0.2 else "🔴" if score < -0.2 else "🟡"
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
            "SELECT computed_at, composite_score FROM engine_composite_signal "
            "ORDER BY computed_at DESC LIMIT 30"
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
