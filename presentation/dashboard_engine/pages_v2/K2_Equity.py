# ruff: noqa: N999
"""K2 — Equity (v8.0). Sostituisce E2_Equities.py."""
from __future__ import annotations

__version__ = "8.0.0"
__all__ = ["body_k2_equity"]

_DEFAULT_TICKERS = ["AAPL", "MSFT", "GOOGL", "NVDA", "SPY", "QQQ"]


def body_k2_equity(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()
    st.title("📊 Mercati — Equity")

    try:
        import plotly.graph_objects as go
        from shared.db.prices_repo import get_prices_repository
        from shared.types import TimeFrame
        repo = get_prices_repository()

        ticker = st.selectbox("Ticker", _DEFAULT_TICKERS)

        df = repo.read_prices(ticker=ticker, timeframe=TimeFrame.D1)
        if df is None or df.empty:
            st.warning(f"Nessun dato per {ticker}. Avvia lo scheduler.")
            return

        df = df.tail(252)
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=df["ts"],
            open=df["open"], high=df["high"],
            low=df["low"],   close=df["close"],
            name=ticker,
        ))
        fig.update_layout(
            height=350, title=ticker,
            margin=dict(l=0, r=0, t=40, b=0),
            xaxis_rangeslider_visible=False,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)

        close = float(df["close"].iloc[-1])
        prev  = float(df["close"].iloc[-2])
        delta = (close - prev) / prev * 100
        high52 = float(df["high"].max())
        low52  = float(df["low"].min())
        c1, c2, c3 = st.columns(3)
        c1.metric("Prezzo", f"{close:.2f}", f"{delta:+.2f}%")
        c2.metric("Max 52W", f"{high52:.2f}")
        c3.metric("Min 52W", f"{low52:.2f}")
    except Exception as exc:
        st.warning(f"Dati non disponibili: {exc}")
