# ruff: noqa: N999
"""K5 — Forex & Options (v8.0). Sostituisce E5_Forex_Options.py."""
from __future__ import annotations

__version__ = "8.0.0"
__all__ = ["body_k5_forex_options"]

_FX_PAIRS = ["EURUSD=X","GBPUSD=X","USDJPY=X","USDCHF=X","AUDUSD=X","DX-Y.NYB"]


def body_k5_forex_options(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()
    st.title("📊 Mercati — Forex & Options")

    try:
        import plotly.graph_objects as go
        from shared.db.prices_repo import get_prices_repository
        from shared.types import TimeFrame
        repo = get_prices_repository()

        st.subheader("💱 FX Majors")
        cols = st.columns(3)
        for i, pair in enumerate(_FX_PAIRS):
            with cols[i % 3]:
                try:
                    df = repo.read_prices(ticker=pair, timeframe=TimeFrame.D1)
                    if df is not None and not df.empty and len(df) >= 2:
                        close = float(df["close"].iloc[-1])
                        prev  = float(df["close"].iloc[-2])
                        delta = (close - prev) / prev * 100
                        st.metric(pair.replace("=X","").replace("-Y.NYB"," Index"),
                                  f"{close:.4f}", f"{delta:+.3f}%")
                    else:
                        st.metric(pair, "N/D")
                except Exception:
                    st.metric(pair, "N/D")

        st.divider()
        st.subheader("📊 VIX Term Structure (opzioni)")
        try:
            from shared.db.duckdb_client import get_duckdb_client
            db = get_duckdb_client()
            rows = db.query(
                "SELECT computed_at, vix_level, regime FROM vix_signals "
                "ORDER BY computed_at DESC LIMIT 1"
            )
            if rows:
                st.metric("VIX 30d", f"{float(rows[0][1]):.2f}")
                st.caption(f"VIX regime: {rows[0][2]} | {rows[0][0]}")
            else:
                st.info("VIX N/D")
        except Exception:
            pass
    except Exception as exc:
        st.warning(f"Dati FX non disponibili: {exc}")