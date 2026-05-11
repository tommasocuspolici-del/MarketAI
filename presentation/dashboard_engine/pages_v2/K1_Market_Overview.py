# ruff: noqa: N999
"""K1 — Market Overview (v8.0). Sostituisce E1_Market_Overview.py."""
from __future__ import annotations

__version__ = "8.0.0"
__all__ = ["body_k1_market_overview"]


def body_k1_market_overview(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    from presentation.ui.components.engine_signal_summary import render_engine_signal_summary
    from presentation.ui.components.regime_composite_badge import render_regime_composite_badge

    require_auth()
    st.title("📊 Mercati — Market Overview")

    # ── Composite Signal (primo elemento come da Roadmap DoD) ──────────────
    st.subheader("🔬 Engine Composite Signal")
    try:
        from shared.db.macro_repo import get_macro_repository
        repo      = get_macro_repository()
        composite = repo.read_composite_signal()
        render_engine_signal_summary(st, composite)
        if composite:
            render_regime_composite_badge(
                st,
                regime=composite.regime,
                credit_stress=composite.credit_stress,
                claims_regime=composite.claims_regime,
                vix_action=None,
            )
    except Exception as exc:
        st.warning(f"Composite signal non disponibile: {exc}")

    st.divider()

    # ── KPI mercati principali ─────────────────────────────────────────────
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
                    close  = float(df["close"].iloc[-1])
                    prev   = float(df["close"].iloc[-2])
                    delta  = (close - prev) / prev * 100
                    col.metric(label, f"{close:.2f}", f"{delta:+.2f}%")
                else:
                    col.metric(label, "N/D")
            except Exception:
                col.metric(label, "N/D")
    except Exception as exc:
        st.warning(f"Prezzi non disponibili: {exc}")
