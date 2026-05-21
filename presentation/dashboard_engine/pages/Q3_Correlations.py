# ruff: noqa: N999
"""Q3 — Correlation Analysis (Blocco D).

Pattern: _load_*() pure + body_correlations() Streamlit.
3 tab: Matrice · Cross-Asset · Lead-Lag
"""
from __future__ import annotations

import pandas as pd

from presentation.ui.cache_policy import CACHE_TTL
from presentation.ui.components import EmptyState
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "1.0.0"
__all__ = ["body_correlations"]

_DEFAULT_TICKERS = ("SPY", "QQQ", "GLD", "TLT", "HYG")


def _load_correlation_report(tickers: tuple[str, ...] = _DEFAULT_TICKERS, days: int = 252) -> dict:
    try:
        from engine.analytics.correlation.analyzer import CorrelationAnalyzer
        from shared.db.prices_repo import PricesRepository
        from shared.db.duckdb_client import get_duckdb_client

        db = get_duckdb_client()
        repo = PricesRepository(db)
        frames = []
        for t in tickers:
            df = repo.read_ohlcv(t, limit=days)
            if not df.empty and "close" in df.columns:
                frames.append(df.set_index("date")["close"].rename(t))

        if len(frames) < 2:
            return {}

        prices = pd.concat(frames, axis=1).dropna()
        report = CorrelationAnalyzer().run(prices)
        return {
            "static":   report.static_corr,
            "dynamic":  report.dynamic_corr,
            "lead_lag": report.lead_lag_pairs,
            "n_assets": report.n_assets,
            "n_obs":    report.n_observations,
        }
    except Exception:
        return {}


def _load_cross_asset_snapshot() -> dict:
    try:
        from engine.analytics.correlation.cross_asset_matrix import CrossAssetMatrix
        from shared.db.prices_repo import PricesRepository
        from shared.db.duckdb_client import get_duckdb_client

        db = get_duckdb_client()
        repo = PricesRepository(db)
        tickers = ("SPY", "TLT", "GLD", "HYG")
        frames = []
        for t in tickers:
            df = repo.read_ohlcv(t, limit=252)
            if not df.empty and "close" in df.columns:
                frames.append(df.set_index("date")["close"].rename(t))
        if len(frames) < 2:
            return {}

        prices = pd.concat(frames, axis=1).dropna()
        returns = prices.pct_change().dropna()
        result = CrossAssetMatrix(client=db).compute(returns)
        return {
            "equity_bond_corr":    result.avg_equity_bond_corr,
            "equity_gold_corr":    result.avg_equity_gold_corr,
            "diversification":     result.diversification_score,
            "correlation_signal":  result.correlation_signal,
            "vix_regime":          result.vix_regime,
            "asset_names":         result.asset_names,
            "matrix":              result.correlation_matrix,
        }
    except Exception:
        return {}


def body_correlations(tokens: DesignTokens) -> None:  # pragma: no cover
    import streamlit as st

    render_section_header("🔗 Correlation Analysis", "Matrice dinamica cross-asset con lead-lag detection")

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="q3_refresh"):
            st.cache_data.clear()
            st.rerun()

    tickers_input = st.multiselect(
        "Tickers",
        ["SPY", "QQQ", "GLD", "TLT", "HYG", "DIA", "IWM", "EEM", "USO", "BTC-USD"],
        default=list(_DEFAULT_TICKERS),
        key="q3_tickers",
        max_selections=8,
    )
    days = st.slider("Periodo (giorni)", 60, 730, 252, key="q3_days")

    tab_matrix, tab_cross, tab_leadlag = st.tabs(["📊 Matrice", "🌐 Cross-Asset", "⏱ Lead-Lag"])

    with tab_matrix:
        _render_matrix_tab(st, tuple(tickers_input), days)

    with tab_cross:
        _render_cross_asset_tab(st, tokens)

    with tab_leadlag:
        _render_leadlag_tab(st)


def _render_matrix_tab(st, tickers: tuple, days: int) -> None:  # pragma: no cover
    from presentation.ui.chart_theme import ChartFactory

    @st.cache_data(ttl=CACHE_TTL.BACKTESTING)
    def _cached(t: tuple, d: int) -> dict:
        return _load_correlation_report(t, d)

    with st.spinner("Calcolo correlazioni..."):
        report = _cached(tickers, days)

    if not report or report["static"].empty:
        EmptyState("Dati insufficienti", hint="Seleziona almeno 2 ticker con dati OHLCV nel DB.", severity="warning").render()
        return

    static = report["static"]
    fig = ChartFactory.correlation_heatmap(static)
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"{report['n_assets']} asset · {report['n_obs']} osservazioni")


def _render_cross_asset_tab(st, tokens: DesignTokens) -> None:  # pragma: no cover
    import numpy as np
    from presentation.ui.chart_theme import ChartFactory

    @st.cache_data(ttl=CACHE_TTL.BACKTESTING)
    def _cached() -> dict:
        return _load_cross_asset_snapshot()

    snap = _cached()

    if not snap:
        EmptyState("Cross-asset non disponibile", hint="Popola OHLCV per SPY/TLT/GLD/HYG.").render()
        return

    render_section_header("🌐 Cross-Asset Matrix")
    cols = st.columns(3)
    with cols[0]:
        v = snap.get("equity_bond_corr")
        st.metric("Equity-Bond corr", f"{v:.2f}" if v is not None else "N/D")
    with cols[1]:
        v = snap.get("diversification")
        st.metric("Diversification Score", f"{v:.2f}" if v is not None else "N/D")
    with cols[2]:
        st.metric("Segnale", f"{snap.get('correlation_signal', 0):+.3f}")

    names = snap.get("asset_names", [])
    matrix = snap.get("matrix")
    if matrix is not None and len(names) >= 2:
        df_cross = pd.DataFrame(matrix, index=names, columns=names)
        fig = ChartFactory.correlation_heatmap(df_cross)
        st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Regime VIX: {snap.get('vix_regime', 'N/D')}")


def _render_leadlag_tab(st) -> None:  # pragma: no cover
    @st.cache_data(ttl=CACHE_TTL.BACKTESTING)
    def _cached() -> dict:
        return _load_correlation_report()

    report = _cached()
    pairs = report.get("lead_lag", [])

    if not pairs:
        EmptyState("Nessuna coppia lead-lag rilevata", hint="Richiede dati OHLCV per i ticker selezionati.").render()
        return

    render_section_header("⏱ Lead-Lag Pairs")
    rows = [
        {"Leader": p.leader, "Follower": p.follower, "Lag (periodi)": p.lag_periods,
         "Correlazione": f"{p.correlation:.3f}", "p-value": f"{p.p_value:.3f}"}
        for p in pairs
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


if __name__ == "__main__":  # pragma: no cover
    render_page("Correlazioni", "🔗", body_correlations)
