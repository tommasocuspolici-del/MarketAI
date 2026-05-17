# ruff: noqa: N999
"""Q5 Delta & Momentum (v8.1) — dati reali da PricesRepo + DuckDB."""
from __future__ import annotations

__version__ = "8.1.0"
__all__ = ["body_q5_delta"]

_WATCH_TICKERS = ["SPY", "QQQ", "GLD", "TLT", "^VIX", "EURUSD=X"]
_LOOKBACKS = [5, 21, 63]  # giorni: 1w, 1m, 3m


def body_q5_delta(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    st.title("🔬 Analisi — Delta & Momentum")
    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="q5_refresh"):
            st.cache_data.clear()
            st.rerun()

    @st.cache_data(ttl=600)
    def _load_delta_table():
        import yfinance as yf
        import pandas as pd

        records = []
        for ticker in _WATCH_TICKERS:
            try:
                hist = yf.Ticker(ticker).history(period="1y")
                if hist.empty or len(hist) < 65:
                    continue
                closes = hist["Close"]
                last = float(closes.iloc[-1])
                row = {"Ticker": ticker, "Last": f"{last:.2f}"}
                for lb in _LOOKBACKS:
                    ref = float(closes.iloc[-lb - 1]) if len(closes) > lb else float(closes.iloc[0])
                    delta_pct = (last - ref) / ref * 100
                    label = f"Δ{lb}d"
                    row[label] = f"{delta_pct:+.1f}%"
                records.append(row)
            except Exception:
                records.append({"Ticker": ticker, "Last": "N/D", **{f"Δ{lb}d": "N/D" for lb in _LOOKBACKS}})

        return pd.DataFrame(records) if records else None

    @st.cache_data(ttl=600)
    def _load_momentum():
        import yfinance as yf
        import pandas as pd
        import numpy as np

        momentum_records = []
        for ticker in _WATCH_TICKERS:
            try:
                hist = yf.Ticker(ticker).history(period="1y")
                if hist.empty or len(hist) < 21:
                    continue
                closes = hist["Close"]
                ret_21d = float((closes.iloc[-1] / closes.iloc[-22] - 1) * 100)
                vol_21d = float(closes.pct_change().tail(21).std() * 100 * (252 ** 0.5))
                momentum_records.append({
                    "Ticker": ticker,
                    "Mom 1M (%)": f"{ret_21d:+.1f}%",
                    "Ann Vol (%)": f"{vol_21d:.1f}%",
                    "Signal": "🟢 MOM+" if ret_21d > 3 else ("🔴 MOM-" if ret_21d < -3 else "⚪ NEUTRO"),
                })
            except Exception:
                pass
        return pd.DataFrame(momentum_records) if momentum_records else None

    st.subheader("📊 Delta Tabella — Variazioni periodiche")
    df_delta = _load_delta_table()
    if df_delta is not None and not df_delta.empty:
        st.dataframe(df_delta, use_container_width=True, hide_index=True)
        st.caption(f"Tickers: {', '.join(_WATCH_TICKERS)} · Δ{_LOOKBACKS[0]}d = 1w, Δ{_LOOKBACKS[1]}d = 1m, Δ{_LOOKBACKS[2]}d = 3m")
    else:
        st.warning("Dati delta non disponibili — verifica connessione internet.")

    st.divider()
    st.subheader("⚡ Momentum Signals")
    df_mom = _load_momentum()
    if df_mom is not None and not df_mom.empty:
        st.dataframe(df_mom, use_container_width=True, hide_index=True)
    else:
        st.warning("Dati momentum non disponibili.")
