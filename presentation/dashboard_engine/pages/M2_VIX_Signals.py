# ruff: noqa: N999
"""M2 — VIX & Volatility (v8.2.0).

Segue il template M1: _load_*() puri · _render_*() pragma: no cover.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from presentation.ui.components import EmptyState, KpiCard
from presentation.ui.layout import setup_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "8.2.0"
__all__ = ["body_vix_signals"]


def _load_vix_series(limit: int = 252) -> pd.DataFrame:
    """Load VIX history from DuckDB or yfinance fallback."""
    try:
        from shared.db.duckdb_client import DuckDBClient
        from shared.db.prices_repo import PricesRepository

        client = DuckDBClient()
        repo = PricesRepository(client)
        df = repo.read_ohlcv("^VIX", limit=limit)
        if not df.empty:
            date_col = next((c for c in ["ts", "date"] if c in df.columns), None)
            val_col = next((c for c in ["close_price", "close"] if c in df.columns), None)
            if date_col and val_col:
                return df[[date_col, val_col]].rename(columns={date_col: "date", val_col: "value"})
    except Exception:
        pass
    return pd.DataFrame(columns=["date", "value"])


def _load_vix_current() -> float | None:
    """Return latest VIX value from LiveMarketService snapshot."""
    try:
        from engine.market_data.live_market_service import get_live_market_service
        snap = get_live_market_service().get_kpi_snapshot()
        kpi = next((k for k in snap.kpis if k.term == "VIX"), None)
        return float(kpi.value) if kpi and kpi.value is not None else None
    except Exception:
        return None


def _vix_to_regime_label(vix: float | None) -> str:
    """Map VIX to a volatility regime label."""
    if vix is None:
        return "Sconosciuto"
    if vix < 12:  return "Compiacenza estrema"
    if vix < 20:  return "Bassa volatilità"
    if vix < 30:  return "Volatilità moderata"
    if vix < 40:  return "Alta volatilità"
    return "Crisi / Panico"


def _render_vix_kpis(st, vix: float | None, tokens: DesignTokens) -> None:  # pragma: no cover
    cols = st.columns(3)
    regime_label = _vix_to_regime_label(vix)
    with cols[0]:
        KpiCard("VIX", vix if vix is not None else "—", tooltip="CBOE Volatility Index").render()
    with cols[1]:
        KpiCard("Regime", regime_label).render()
    with cols[2]:
        from presentation.dashboard_engine.pages.E1_Market_Overview import _derive_regime
        market_regime = _derive_regime(vix)
        color = tokens.colors.regime_color(market_regime)
        st.markdown(
            f'**Mercato:** <span style="color:{color}">{market_regime.upper()}</span>',
            unsafe_allow_html=True,
        )


def _render_chart(st, tokens: DesignTokens) -> None:  # pragma: no cover
    from presentation.ui.chart_theme import ChartFactory

    df = _load_vix_series()
    if df.empty:
        EmptyState("Storico VIX non disponibile",
                   hint="I dati VIX vengono caricati da Yahoo Finance.", severity="info").render()
        return

    fig = ChartFactory.time_series(
        df, x_col="date", y_col="value",
        title="VIX — Storico",
        color=tokens.colors.chart_accent,
    )
    st.plotly_chart(fig, use_container_width=True)


def body_vix_signals(tokens: DesignTokens) -> None:  # pragma: no cover
    import streamlit as st

    h_col, r_col = st.columns([5, 1])
    with h_col:
        st.markdown("## 🌡️ VIX & Volatility")
    with r_col:
        if st.button("🔄 Aggiorna", key="m2_refresh"):
            st.cache_data.clear()
            st.rerun()

    vix = _load_vix_current()
    _render_vix_kpis(st, vix, tokens)
    st.divider()
    _render_chart(st, tokens)


if __name__ == "__main__":  # pragma: no cover
    tokens = setup_page("M2 VIX & Volatility", icon="🌡️")
    body_vix_signals(tokens)
