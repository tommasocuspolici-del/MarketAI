# ruff: noqa: N999
"""M4 — Yield Curve (v8.2.0).

Segue il template M1: _load_*() puri · _render_*() pragma: no cover.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from presentation.ui.components import EmptyState, KpiCard
from presentation.ui.layout import setup_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "8.2.0"
__all__ = ["body_yield_curve"]


@dataclass
class YieldSnapshot:
    t2y: float | None = None
    t10y: float | None = None
    spread_bp: float | None = None
    is_inverted: bool = False


def _load_yield_snapshot() -> YieldSnapshot:
    """Load 2Y/10Y yields and compute spread from FRED."""
    try:
        from engine.market_data.fred_simple_client import FredSimpleClient

        fred = FredSimpleClient()
        if not fred.has_api_key:
            return YieldSnapshot()

        t10_res = fred.fetch_latest("DGS10")
        t2_res  = fred.fetch_latest("DGS2")

        t10 = float(t10_res[1]) if t10_res else None
        t2  = float(t2_res[1])  if t2_res  else None

        spread = round((t10 - t2) * 100, 1) if t10 is not None and t2 is not None else None
        return YieldSnapshot(
            t2y=round(t2, 3) if t2 else None,
            t10y=round(t10, 3) if t10 else None,
            spread_bp=spread,
            is_inverted=(spread < 0) if spread is not None else False,
        )
    except Exception:
        return YieldSnapshot()


def _load_yield_series(series_id: str = "DGS10", limit: int = 252) -> pd.DataFrame:
    """Load yield time series from FRED (or DuckDB cache)."""
    try:
        from shared.db.duckdb_client import DuckDBClient
        from shared.db.macro_repo import MacroRepo

        df = MacroRepo(DuckDBClient()).read_series(series_id, limit=limit)
        if df is not None and not df.empty:
            dc = next((c for c in ["ts", "date"] if c in df.columns), None)
            vc = next((c for c in ["value", "val"] if c in df.columns), None)
            if dc and vc:
                return df[[dc, vc]].rename(columns={dc: "date", vc: "value"})
    except Exception:
        pass
    return pd.DataFrame(columns=["date", "value"])


def _render_yield_kpis(st, snap: YieldSnapshot, tokens: DesignTokens) -> None:  # pragma: no cover
    cols = st.columns(3)
    with cols[0]:
        KpiCard("Yield 2Y", snap.t2y if snap.t2y else "—", unit="%").render()
    with cols[1]:
        KpiCard("Yield 10Y", snap.t10y if snap.t10y else "—", unit="%").render()
    with cols[2]:
        if snap.spread_bp is not None:
            label = f"{'⚠️ Invertita' if snap.is_inverted else 'Normale'}"
            KpiCard("Spread 10Y-2Y", snap.spread_bp, unit=" bp",
                    tooltip=label).render()
            if snap.is_inverted:
                st.warning("⚠️ Curva invertita — segnale recessivo storico.")
        else:
            KpiCard("Spread", "—", tooltip="Configura FRED_API_KEY").render()


def _render_chart(st, tokens: DesignTokens) -> None:  # pragma: no cover
    from presentation.ui.chart_theme import ChartFactory

    tab_10y, tab_2y, tab_spread = st.tabs(["📈 Yield 10Y", "📊 Yield 2Y", "⚖️ Spread"])

    with tab_10y:
        df = _load_yield_series("DGS10")
        if df.empty:
            EmptyState("Yield 10Y non disponibile", hint="Configura FRED_API_KEY.", severity="info").render()
        else:
            st.plotly_chart(ChartFactory.time_series(df, "date", "value",
                title="US Treasury 10Y", color=tokens.colors.chart_primary), use_container_width=True)

    with tab_2y:
        df = _load_yield_series("DGS2")
        if df.empty:
            EmptyState("Yield 2Y non disponibile", hint="Configura FRED_API_KEY.", severity="info").render()
        else:
            st.plotly_chart(ChartFactory.time_series(df, "date", "value",
                title="US Treasury 2Y", color=tokens.colors.chart_secondary), use_container_width=True)

    with tab_spread:
        EmptyState("Spread storico", hint="Calcolo spread 10Y-2Y storico non ancora implementato.", severity="info").render()


def body_yield_curve(tokens: DesignTokens) -> None:  # pragma: no cover
    import streamlit as st

    h_col, r_col = st.columns([5, 1])
    with h_col:
        st.markdown("## 📉 Yield Curve")
    with r_col:
        if st.button("🔄 Aggiorna", key="m4_refresh"):
            st.cache_data.clear()
            st.rerun()

    snap = _load_yield_snapshot()
    _render_yield_kpis(st, snap, tokens)
    st.divider()
    _render_chart(st, tokens)


if __name__ == "__main__":  # pragma: no cover
    tokens = setup_page("M4 Yield Curve", icon="📉")
    body_yield_curve(tokens)
