# ruff: noqa: N999
"""E1 — Market Overview (v8.2.0).

Rebuild con component library:
  - 8 KpiCard live da LiveMarketService (S&P500, VIX, Yield 10Y, DXY,
    EUR/USD, Gold, Oil WTI, BTC)
  - 3 tab chart (lazy loaded): S&P500 12M + regime shading |
    Macro Signal Breakdown | Sector Performance
  - Sidebar segnali: SignalRegistry snapshot (SignalBadge ×N) + regime pill

Design: _load_*() puri e testabili · _render_*() pragma: no cover.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from presentation.ui.components import EmptyState, KpiCard, SignalBadge
from presentation.ui.layout import setup_page
from presentation.ui.session_keys import SK

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "8.2.0"
__all__ = ["body_market_overview"]


# ─────────────────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class KpiData:
    """Intermediate data model between MarketKpi and KpiCard."""
    title: str
    value: float | str
    unit: str
    delta: float | None
    quality_flag: str
    icon: str


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers — testable without Streamlit
# ─────────────────────────────────────────────────────────────────────────────

def _derive_regime(vix_value: float | None) -> str:
    """Map VIX level to a market regime label.

    Args:
        vix_value: Current VIX index level, or None if unavailable.

    Returns:
        One of: "bull" | "transition" | "bear" | "stress" | "unknown".
    """
    if vix_value is None:
        return "unknown"
    v = float(vix_value)
    if v > 30:
        return "stress"
    if v > 25:
        return "bear"
    if v > 15:
        return "transition"
    return "bull"


def _snapshot_to_kpi_data(snapshot) -> list[KpiData]:
    """Convert a MarketSnapshot into KpiData list for rendering.

    Preserves the original order from LiveMarketService but falls back to
    a safe "—" value when a KPI could not be fetched.
    """
    _ICONS: dict[str, str] = {
        "S&P 500": "📈", "VIX": "🌡️", "Yield 10Y": "📊", "DXY": "💵",
        "EUR/USD": "🇪🇺", "Gold": "🥇", "Oil WTI": "🛢️", "BTC/USD": "₿",
    }
    result: list[KpiData] = []
    for kpi in snapshot.kpis:
        value: float | str = "—" if kpi.value is None else kpi.value
        unit = f" {kpi.currency}" if kpi.currency and kpi.currency != "—" else ""
        flag = "stale" if kpi.is_stale else ("ok" if kpi.value is not None else "insufficient_data")
        result.append(KpiData(
            title=kpi.term,
            value=value,
            unit=unit,
            delta=kpi.delta_pct,
            quality_flag=flag,
            icon=_ICONS.get(kpi.term, ""),
        ))
    return result


def _load_signal_snapshot() -> dict[str, tuple[float, float | None, str]]:
    """Load current signal values from SignalRegistry.

    Returns:
        {signal_name: (value, ic_estimate, quality_flag)}
    """
    from shared.signal_registry import get_signal_registry

    registry = get_signal_registry()
    result: dict[str, tuple[float, float | None, str]] = {}
    for name in registry.all_signals():
        sig = registry.get(name)
        if sig is None:
            continue
        stale = name in registry.stale_signals()
        flag = "stale" if stale else sig.quality_flag
        result[name] = (sig.value, sig.ic_estimate, flag)
    return result


def _load_sp500_history(days: int = 365) -> pd.DataFrame:
    """Load S&P500 OHLCV history from DuckDB (PricesRepo).

    Returns:
        DataFrame with columns [date, close] or empty DataFrame.
    """
    try:
        from shared.db.duckdb_client import DuckDBClient
        from shared.db.prices_repo import PricesRepository
        client = DuckDBClient()
        repo = PricesRepository(client)
        df = repo.read_ohlcv("^GSPC", limit=days + 10)
        if df.empty:
            return pd.DataFrame(columns=["date", "close"])
        df = df.rename(columns={"ts": "date", "close_price": "close"})
        return df[["date", "close"]].sort_values("date").tail(days).reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=["date", "close"])


def _build_regime_df_from_vix(vix_value: float | None) -> pd.DataFrame:
    """Build a minimal regime DataFrame for overlay (single-period).

    When full historical HMM regime data is unavailable, derive a single-
    segment regime from the current VIX level so regime_shade still shows
    the *current* market color on the chart.
    """
    if vix_value is None:
        return pd.DataFrame()
    import datetime
    today = pd.Timestamp.today().normalize()
    start = today - pd.Timedelta(days=365)
    return pd.DataFrame({"date": [start, today], "regime": [_derive_regime(vix_value)] * 2})


# ─────────────────────────────────────────────────────────────────────────────
# Renderers — pragma: no cover
# ─────────────────────────────────────────────────────────────────────────────

def _render_kpi_grid(st, kpi_data: list[KpiData]) -> None:  # pragma: no cover
    """Render two rows of 4 KpiCard each."""
    row1 = kpi_data[:4]
    row2 = kpi_data[4:8]

    cols1 = st.columns(len(row1)) if row1 else []
    for col, kpi in zip(cols1, row1):
        with col:
            KpiCard(
                title=kpi.title, value=kpi.value, unit=kpi.unit,
                delta=kpi.delta, quality_flag=kpi.quality_flag, icon=kpi.icon,
            ).render()

    if row2:
        cols2 = st.columns(len(row2))
        for col, kpi in zip(cols2, row2):
            with col:
                KpiCard(
                    title=kpi.title, value=kpi.value, unit=kpi.unit,
                    delta=kpi.delta, quality_flag=kpi.quality_flag, icon=kpi.icon,
                ).render()


def _render_tab_sp500(st, vix_value: float | None) -> None:  # pragma: no cover
    """Tab 1 — S&P500 12M con regime shading."""
    from presentation.ui.chart_theme import ChartFactory, regime_shade

    sp500_df = _load_sp500_history(days=365)
    if sp500_df.empty:
        EmptyState(
            "Nessun dato S&P500 in DuckDB",
            hint="Avvia un fetch da Yahoo Finance per popolare la serie storica.",
            severity="info",
        ).render()
        return

    regime_df = _build_regime_df_from_vix(vix_value)
    fig = ChartFactory.time_series(
        sp500_df, x_col="date", y_col="close",
        title="S&P 500 — ultimi 12 mesi",
        color=None, y_format="number",
        regime_df=regime_df if not regime_df.empty else None,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_tab_macro(st) -> None:  # pragma: no cover
    """Tab 2 — Macro Signal Breakdown (SignalRegistry)."""
    from presentation.ui.chart_theme import ChartFactory

    signals = _load_signal_snapshot()
    if not signals:
        EmptyState(
            "Nessun segnale macro disponibile",
            hint="I segnali vengono aggiornati automaticamente dal pipeline analitico.",
            severity="info",
        ).render()
        return

    signals_for_chart = {name: (val, ic) for name, (val, ic, _) in signals.items()}
    fig = ChartFactory.signal_breakdown(
        signals_for_chart,
        title="Macro Signal Breakdown",
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_tab_sectors(st) -> None:  # pragma: no cover
    """Tab 3 — Sector Performance (ETF YTD %)."""
    import plotly.graph_objects as go
    from presentation.ui.chart_theme import get_base_layout
    from presentation.ui.design_tokens import TOKENS

    @st.cache_data(ttl=3600)
    def _fetch_sectors() -> dict[str, float | None]:
        try:
            import yfinance as yf
            etfs = {
                "Technology": "XLK", "Healthcare": "XLV", "Financials": "XLF",
                "Energy": "XLE", "Industrials": "XLI", "Consumer Disc.": "XLY",
            }
            result = {}
            for label, ticker in etfs.items():
                try:
                    info = yf.Ticker(ticker).fast_info
                    ytd = getattr(info, "year_change", None)
                    result[label] = round(ytd * 100, 2) if ytd is not None else None
                except Exception:
                    result[label] = None
            return result
        except Exception:
            return {}

    sectors = _fetch_sectors()
    valid = {k: v for k, v in sectors.items() if v is not None}

    if not valid:
        EmptyState(
            "Dati settoriali non disponibili",
            hint="Verifica la connessione a Yahoo Finance.",
            severity="warning",
        ).render()
        return

    names = list(valid.keys())
    values = [valid[n] for n in names]
    colors = [TOKENS.colors.signal_color(v / 30) for v in values]  # normalize ±30% → ±1

    fig = go.Figure(go.Bar(
        y=names, x=values, orientation="h",
        marker_color=colors,
        text=[f"{v:+.1f}%" for v in values],
        textposition="outside",
        hovertemplate="<b>%{y}</b>: %{x:+.1f}%<extra></extra>",
    ))
    fig.add_vline(x=0, line_width=1, line_color=TOKENS.colors.text_muted)
    layout = get_base_layout(title={"text": "Sector Performance YTD", "font": {"size": 14}})
    layout["xaxis"]["tickformat"] = "+.1f"
    fig.update_layout(**layout)
    st.plotly_chart(fig, use_container_width=True)


def _render_signals_sidebar(st, tokens: DesignTokens) -> None:  # pragma: no cover
    """Right column: signal badges + regime pill."""
    signals = _load_signal_snapshot()

    if not signals:
        EmptyState(
            "Segnali non disponibili",
            hint="Pipeline non ancora eseguita.",
            severity="info",
        ).render()
        return

    composite_val = signals.get("composite_signal", signals.get("macro_conviction"))
    if composite_val:
        c_val, c_ic, c_flag = composite_val
        st.markdown(f"**Composito:** {c_val:+.3f}")

    st.markdown("**Segnali:**")
    for name, (val, ic, flag) in sorted(signals.items()):
        SignalBadge(name=name, value=val, ic_estimate=ic, quality_flag=flag).render()


def _render_refresh_status(st, snapshot) -> None:  # pragma: no cover
    """Status bar + refresh button."""
    col_status, col_btn = st.columns([4, 1])
    n_ok = sum(1 for k in snapshot.kpis if k.value is not None)
    n_total = len(snapshot.kpis)
    with col_status:
        if n_ok == n_total:
            st.success(f"✅ {n_total} KPI aggiornati · {snapshot.fetched_at_human}")
        elif n_ok > 0:
            st.warning(f"⚠️ {n_ok}/{n_total} KPI · {snapshot.n_errors} errori · {snapshot.fetched_at_human}")
        else:
            st.error(f"❌ Dati non disponibili · {snapshot.fetched_at_human}")
    with col_btn:
        if st.button("🔄 Aggiorna", key="e1_refresh", use_container_width=True):
            st.session_state[SK.FORCE_REFRESH] = True
            st.cache_data.clear()
            st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def body_market_overview(tokens: DesignTokens) -> None:  # pragma: no cover
    """E1 Market Overview — KPI grid + 3-tab charts + signals sidebar."""
    import streamlit as st
    from engine.market_data.live_market_service import get_live_market_service

    svc = get_live_market_service()

    # Force refresh if requested
    if st.session_state.pop(SK.FORCE_REFRESH, False):
        snapshot = svc.refresh_now()
        st.cache_data.clear()
    else:
        snapshot = svc.get_kpi_snapshot()

    st.markdown("## 🌍 Market Overview")
    _render_refresh_status(st, snapshot)

    # ── KPI grid ────────────────────────────────────────────────────────────
    kpi_data = _snapshot_to_kpi_data(snapshot)
    _render_kpi_grid(st, kpi_data)

    st.divider()

    # ── Charts + Signals (2-column layout) ──────────────────────────────────
    vix_kpi = next((k for k in snapshot.kpis if k.term == "VIX"), None)
    vix_value = float(vix_kpi.value) if vix_kpi and vix_kpi.value is not None else None
    current_regime = _derive_regime(vix_value)

    col_charts, col_signals = st.columns([3, 1])

    with col_charts:
        tab_sp500, tab_macro, tab_sectors = st.tabs([
            "📈 S&P 500 12M", "📊 Macro Signals", "🏭 Settori"
        ])
        with tab_sp500:
            _render_tab_sp500(st, vix_value)
        with tab_macro:
            _render_tab_macro(st)
        with tab_sectors:
            _render_tab_sectors(st)

    with col_signals:
        # Regime pill
        regime_colors = {
            "bull": tokens.colors.regime_bull, "bear": tokens.colors.regime_bear,
            "stress": tokens.colors.regime_stress, "transition": tokens.colors.regime_transition,
            "unknown": tokens.colors.neutral,
        }
        rc = regime_colors.get(current_regime, tokens.colors.neutral)
        st.markdown(
            f'**Regime:** <span style="color:{rc};font-weight:600">'
            f'{current_regime.upper()}</span>',
            unsafe_allow_html=True,
        )
        if vix_value:
            st.caption(f"VIX: {vix_value:.1f}")
        st.divider()
        _render_signals_sidebar(st, tokens)


if __name__ == "__main__":  # pragma: no cover
    tokens = setup_page("E1 Market Overview", icon="🌍")
    body_market_overview(tokens)
