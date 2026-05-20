# ruff: noqa: N999
"""M1 — Macro Conviction (v8.2.0).

Template di riferimento per tutte le pagine M*.

Pattern:
  _load_macro_data()  → MacroConvictionResult  (testabile, no Streamlit)
  _render_kpi_row()   → KpiCard grid            (pragma: no cover)
  _render_chart()     → ChartFactory            (pragma: no cover)
  body_macro_signals() → orchestrator < 30 righe (pragma: no cover)
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
__all__ = ["body_macro_signals"]


@dataclass
class MacroKpiRow:
    label: str
    value: float | str
    unit: str
    delta: float | None


def _load_macro_data() -> list[MacroKpiRow]:
    """Load macro KPIs from MacroConvictionCalculator.

    Returns empty list gracefully on DB or API errors.
    """
    try:
        from engine.alpha_generation.macro_conviction import MacroConvictionCalculator
        from shared.db.duckdb_client import DuckDBClient
        from shared.db.macro_repo import MacroRepo

        client = DuckDBClient()
        repo = MacroRepo(client)
        result = MacroConvictionCalculator(macro_repo=repo).compute()

        rows: list[MacroKpiRow] = []
        if result.gdp_growth_pct is not None:
            rows.append(MacroKpiRow("GDP Growth", round(result.gdp_growth_pct, 2), "%", None))
        if result.inflation_cpi_yoy is not None:
            rows.append(MacroKpiRow("CPI YoY", round(result.inflation_cpi_yoy, 2), "%", None))
        if result.unemployment_rate is not None:
            rows.append(MacroKpiRow("Unemployment", round(result.unemployment_rate, 1), "%", None))
        if result.macro_score is not None:
            rows.append(MacroKpiRow("Macro Score", round(result.macro_score, 3), "", None))
        return rows
    except Exception:
        return []


def _load_macro_series(series_id: str = "UNRATE", limit: int = 60) -> pd.DataFrame:
    """Load a macro time series from DuckDB (MacroRepo).

    Returns DataFrame with [date, value] or empty DataFrame on error.
    """
    try:
        from shared.db.duckdb_client import DuckDBClient
        from shared.db.macro_repo import MacroRepo

        client = DuckDBClient()
        repo = MacroRepo(client)
        df = repo.read_series(series_id, limit=limit)
        if df is None or df.empty:
            return pd.DataFrame(columns=["date", "value"])
        date_col = next((c for c in ["ts", "date", "period"] if c in df.columns), None)
        val_col = next((c for c in ["value", "val"] if c in df.columns), None)
        if not date_col or not val_col:
            return pd.DataFrame(columns=["date", "value"])
        return df[[date_col, val_col]].rename(columns={date_col: "date", val_col: "value"})
    except Exception:
        return pd.DataFrame(columns=["date", "value"])


def _render_kpi_row(st, rows: list[MacroKpiRow]) -> None:  # pragma: no cover
    cols = st.columns(min(len(rows), 4))
    for col, row in zip(cols, rows[:4]):
        with col:
            KpiCard(row.label, row.value, unit=row.unit, delta=row.delta).render()


def _render_chart(st, tokens: DesignTokens) -> None:  # pragma: no cover
    from presentation.ui.chart_theme import ChartFactory
    from presentation.dashboard_engine.pages.E1_Market_Overview import _derive_regime
    from shared.signal_registry import get_signal_registry

    tab_gdp, tab_inflation, tab_unemployment = st.tabs([
        "📈 GDP Growth", "📊 Inflazione", "👷 Occupazione"
    ])

    registry = get_signal_registry()
    vix_sig = registry.get("vix_signal")
    regime = _derive_regime(-30 * (vix_sig.value if vix_sig else 0) + 20) if vix_sig else "transition"

    with tab_gdp:
        df = _load_macro_series("A191RL1Q225SBEA", limit=40)
        if df.empty:
            EmptyState("GDP Growth non disponibile", hint="Carica dati FRED.", severity="info").render()
        else:
            st.plotly_chart(ChartFactory.time_series(df, "date", "value",
                title="Real GDP Growth Rate (QoQ Ann.)", y_format="percent"), use_container_width=True)

    with tab_inflation:
        df = _load_macro_series("CPIAUCSL", limit=60)
        if df.empty:
            EmptyState("CPI non disponibile", hint="Carica dati FRED.", severity="info").render()
        else:
            st.plotly_chart(ChartFactory.time_series(df, "date", "value",
                title="CPI All Urban Consumers", color=tokens.colors.chart_accent), use_container_width=True)

    with tab_unemployment:
        df = _load_macro_series("UNRATE", limit=60)
        if df.empty:
            EmptyState("UNRATE non disponibile", hint="Carica dati FRED.", severity="info").render()
        else:
            st.plotly_chart(ChartFactory.time_series(df, "date", "value",
                title="Unemployment Rate (%)", color=tokens.colors.chart_secondary), use_container_width=True)


def body_macro_signals(tokens: DesignTokens) -> None:  # pragma: no cover
    """M1 Macro Conviction — orchestrator."""
    import streamlit as st

    h_col, r_col = st.columns([5, 1])
    with h_col:
        st.markdown("## 🌐 Macro Conviction")
    with r_col:
        if st.button("🔄 Aggiorna", key="m1_refresh"):
            st.cache_data.clear()
            st.rerun()

    rows = _load_macro_data()
    if rows:
        _render_kpi_row(st, rows)
    else:
        EmptyState("Dati macro non disponibili", hint="Avvia il fetch da FRED.", severity="warning").render()

    st.divider()
    _render_chart(st, tokens)


if __name__ == "__main__":  # pragma: no cover
    tokens = setup_page("M1 Macro Conviction", icon="🌐")
    body_macro_signals(tokens)
