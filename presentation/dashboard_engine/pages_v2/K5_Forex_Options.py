# ruff: noqa: N999
"""K5 — Forex & Options (v8.1). Sostituisce E5_Forex_Options.py."""
from __future__ import annotations

__version__ = "8.1.0"
__all__ = ["body_k5_forex_options"]

_FX_PAIRS = ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDCHF=X", "AUDUSD=X", "DX-Y.NYB"]


def _load_fx_prices() -> dict[str, tuple[float, float] | None]:
    from shared.db.prices_repo import get_prices_repository
    from shared.types import TimeFrame
    repo = get_prices_repository()
    out: dict[str, tuple[float, float] | None] = {}
    for pair in _FX_PAIRS:
        try:
            df = repo.read_prices(ticker=pair, timeframe=TimeFrame.D1)
            if df is not None and not df.empty and len(df) >= 2:
                close = float(df["close"].iloc[-1])
                prev  = float(df["close"].iloc[-2])
                out[pair] = (close, prev)
            else:
                out[pair] = None
        except Exception:
            out[pair] = None
    return out


def _load_vix_signal() -> tuple[float, str, object] | None:
    from shared.db.duckdb_client import get_duckdb_client
    db = get_duckdb_client()
    rows = db.query(
        "SELECT computed_at, vix_level, regime FROM vix_signals "
        "ORDER BY computed_at DESC LIMIT 1"
    )
    if rows:
        return (float(rows[0][1]), str(rows[0][2]), rows[0][0])
    return None


def body_k5_forex_options(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    from presentation.ui.cache_policy import CACHE_TTL
    import plotly.graph_objects as go

    require_auth()
    st.title("📊 Mercati — Forex & Options")
    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="k5_refresh"):
            st.cache_data.clear()
            st.rerun()

    # ── FX Majors ─────────────────────────────────────────────────────────────
    st.subheader("💱 FX Majors")
    try:
        cached_fx = st.cache_data(ttl=CACHE_TTL.MARKET_KPI)(_load_fx_prices)
        fx_data = cached_fx()
        cols = st.columns(3)
        for i, pair in enumerate(_FX_PAIRS):
            with cols[i % 3]:
                prices = fx_data.get(pair)
                if prices:
                    close, prev = prices
                    delta = (close - prev) / prev * 100
                    label = pair.replace("=X", "").replace("-Y.NYB", " Index")
                    st.metric(label, f"{close:.4f}", f"{delta:+.3f}%")
                else:
                    label = pair.replace("=X", "").replace("-Y.NYB", " Index")
                    st.metric(label, "N/D")
    except Exception as exc:
        st.warning(f"Dati FX non disponibili: {exc}")

    st.divider()

    # ── VIX Term Structure (opzioni) ────────────────────────────────────────
    st.subheader("📊 VIX Term Structure (opzioni)")
    try:
        cached_vix = st.cache_data(ttl=CACHE_TTL.MARKET_KPI)(_load_vix_signal)
        vix = cached_vix()
        if vix:
            vix_level, regime, computed_at = vix
            st.metric("VIX 30d", f"{vix_level:.2f}")
            st.caption(f"VIX regime: {regime} | {computed_at}")
        else:
            st.info("⚠️ Dati VIX non ancora disponibili — avviare lo scheduler per popolare vix_signals.")
    except Exception as exc:
        st.warning(f"VIX non disponibile: {exc}")
