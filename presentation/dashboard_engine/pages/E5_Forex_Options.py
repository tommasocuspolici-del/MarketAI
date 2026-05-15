# ruff: noqa: N999
"""E5 — Forex & Options (v7.1.2 hotfix).

Risolve "VIX hardcoded a 16.5 e FX heatmap random" segnalato in
ULTERIORI_ERRORI.txt. Ora:

  - VIX, EUR/USD, DXY letti da ``LiveMarketService`` (gia' fetcha real-time
    via yfinance).
  - FX heatmap calcolata dai prezzi reali yfinance dei cross majors
    (variazione % settimanale), non piu' valori random.
  - Fallback graceful se yfinance non installato o se mancano dati.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from engine.market_data.live_market_service import (
    MarketKpi,
    get_live_market_service,
)
from presentation.ui.cache_policy import CACHE_TTL
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.1.2"

__all__ = ["body_forex_options"]

# Pairs majors per heatmap. Yahoo usa il formato CCYxCCY=X.
# Costruiamo la matrice cross calcolando pct change settimanale.
_FX_MAJORS: tuple[str, ...] = ("USD", "EUR", "GBP", "JPY", "CHF", "CAD")

# Cross che useremo per stimare il movimento di ogni currency vs un benchmark.
# Per ogni cross "BASEQUOTE", una variazione % positiva implica BASE rafforzato
# vs QUOTE. Yahoo ticker convention: "EURUSD=X" ritorna EUR/USD prezzo.
_FX_USD_CROSSES: dict[str, str] = {
    "EUR": "EURUSD=X",   # 1 EUR = X USD
    "GBP": "GBPUSD=X",
    "JPY": "USDJPY=X",   # invertiamo dopo (movimento JPY = -movimento USD/JPY)
    "CHF": "USDCHF=X",   # idem
    "CAD": "USDCAD=X",   # idem
}


def _fetch_fx_changes_weekly() -> dict[str, float]:
    """Per ogni currency in _FX_MAJORS, ritorna il pct change su 5d vs USD.

    USD e' il numerario: il suo "change" e' 0 per definizione (matrice
    relative agli altri).
    """
    try:
        import yfinance as yf
    except ImportError:
        return {}

    out: dict[str, float] = {"USD": 0.0}
    tickers = list(_FX_USD_CROSSES.values())
    if not tickers:
        return out

    try:
        data = yf.download(
            tickers=" ".join(tickers),
            period="6d",
            interval="1d",
            progress=False,
            auto_adjust=False,
            threads=True,
            group_by="ticker",
        )
    except (OSError, ValueError, KeyError):
        return out

    if data is None or data.empty:
        return out

    # Itera ogni ticker e calcola pct change su 5d
    for ccy, ticker_yf in _FX_USD_CROSSES.items():
        try:
            if isinstance(data.columns, pd.MultiIndex):
                close_series = data[ticker_yf]["Close"]
            else:  # pragma: no cover - single ticker fallback
                close_series = data["Close"]
        except (KeyError, IndexError):
            continue
        close_series = close_series.dropna()
        if len(close_series) < 2:
            continue
        first, last = float(close_series.iloc[0]), float(close_series.iloc[-1])
        if first == 0:
            continue
        pct = (last - first) / first * 100.0
        # Per i ticker invertiti (USD/CCY), il rafforzamento di USD e'
        # variazione positiva del cross. Quindi CCY si e' indebolita di
        # circa -pct vs USD.
        if ticker_yf.startswith("USD"):
            out[ccy] = -pct
        else:
            out[ccy] = pct
    return out


def _build_cross_matrix(changes_vs_usd: dict[str, float]) -> np.ndarray | None:
    """Costruisce matrice 6x6 con variazione % cross-currency settimanale.

    Cross[i][j] = variazione % di MAJORS[i] vs MAJORS[j] sull'ultima settimana,
    calcolata come (change_i_vs_usd - change_j_vs_usd) — approssimazione
    valida per piccoli movimenti (linearita' dei log-returns).

    Ritorna None se troppi dati mancanti.
    """
    if len(changes_vs_usd) < 4:  # almeno 4 valute con dati
        return None
    n = len(_FX_MAJORS)
    matrix = np.zeros((n, n), dtype=np.float64)
    for i, ccy_i in enumerate(_FX_MAJORS):
        for j, ccy_j in enumerate(_FX_MAJORS):
            if i == j:
                matrix[i][j] = 0.0
                continue
            ci = changes_vs_usd.get(ccy_i)
            cj = changes_vs_usd.get(ccy_j)
            if ci is None or cj is None:
                matrix[i][j] = np.nan
            else:
                matrix[i][j] = ci - cj
    return matrix


def _cached_fetch_fx() -> tuple[np.ndarray | None, dict[str, float]]:
    """Wrapper con cache Streamlit (TTL 30 min)."""
    try:
        import streamlit as st

        @st.cache_data(ttl=CACHE_TTL.FOREX_COMMODITY, show_spinner=False)
        def _fn() -> tuple[np.ndarray | None, dict[str, float]]:
            changes = _fetch_fx_changes_weekly()
            matrix = _build_cross_matrix(changes)
            return matrix, changes

        return _fn()
    except ImportError:  # pragma: no cover
        changes = _fetch_fx_changes_weekly()
        matrix = _build_cross_matrix(changes)
        return matrix, changes


def _find_kpi(kpis: list[MarketKpi], term: str) -> MarketKpi | None:
    """Cerca un KPI per term name (case-sensitive perche' definito in glossario)."""
    for k in kpis:
        if k.term == term:
            return k
    return None


def body_forex_options(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit
    try:
        import plotly.graph_objects as go
        import streamlit as st
    except ImportError:
        return

    # ── 1. FX Heatmap reale ──────────────────────────────────────────────
    render_section_header(
        "💱 FX Majors Cross Heatmap",
        "Variazione % cross-currency sull'ultima settimana (dati yfinance)",
    )

    matrix, changes_vs_usd = _cached_fetch_fx()

    if matrix is None or np.isnan(matrix).all():
        st.error(
            "❌ **FX heatmap non disponibile.** Probabilmente `yfinance` non e' "
            "installato o i tassi cross non sono raggiungibili. "
            "Esegui `poetry install` per ripristinare le dipendenze."
        )
    else:
        fig = go.Figure(
            go.Heatmap(
                z=matrix,
                x=list(_FX_MAJORS),
                y=list(_FX_MAJORS),
                colorscale="RdYlGn",
                zmid=0,
                colorbar={"title": "% week"},
                hoverongaps=False,
            )
        )
        fig.update_layout(
            template=tokens.plotly.template,
            paper_bgcolor=tokens.plotly.paper_bgcolor,
            plot_bgcolor=tokens.plotly.plot_bgcolor,
            height=tokens.plotly.height_md,
            font={
                "family": tokens.plotly.font_family,
                "color": tokens.plotly.font_color,
            },
        )
        st.plotly_chart(fig, use_container_width=True)

        # Mostra il rendimento di ogni valuta vs USD
        cols_fx = st.columns(len(_FX_MAJORS))
        for col, ccy in zip(cols_fx, _FX_MAJORS, strict=True):
            chg = changes_vs_usd.get(ccy)
            with col:
                if chg is None:
                    st.metric(ccy, "—")
                else:
                    st.metric(ccy, f"{chg:+.2f}%", delta=f"{chg:+.2f}%")

    # ── 2. Options Sentiment (VIX da LiveMarketService) ─────────────────
    st.divider()
    render_section_header(
        "🌡️ Options & Volatility",
        "VIX e indicatori di sentiment derivati da opzioni",
    )

    svc = get_live_market_service()
    snapshot = svc.get_kpi_snapshot()
    vix_kpi = _find_kpi(snapshot.kpis, "VIX")
    eurusd_kpi = _find_kpi(snapshot.kpis, "EUR/USD")
    dxy_kpi = _find_kpi(snapshot.kpis, "DXY")

    cols = st.columns(3)
    if vix_kpi is not None and vix_kpi.value is not None:
        regime = (
            "Bassa volatilita'"
            if vix_kpi.value < 15
            else "Normale" if vix_kpi.value < 22
            else "Alta volatilita'" if vix_kpi.value < 30
            else "Stress"
        )
        cols[0].metric(
            "VIX",
            f"{vix_kpi.value:.2f}",
            delta=(
                f"{vix_kpi.delta_pct:+.2f}%"
                if vix_kpi.delta_pct is not None
                else None
            ),
            help=f"Regime: {regime}",
        )
    else:
        cols[0].metric("VIX", "—", help="Dati VIX non disponibili")

    if eurusd_kpi is not None and eurusd_kpi.value is not None:
        cols[1].metric(
            "EUR/USD",
            f"{eurusd_kpi.value:.4f}",
            delta=(
                f"{eurusd_kpi.delta_pct:+.3f}%"
                if eurusd_kpi.delta_pct is not None
                else None
            ),
        )
    else:
        cols[1].metric("EUR/USD", "—")

    if dxy_kpi is not None and dxy_kpi.value is not None:
        cols[2].metric(
            "DXY (Dollar Index)",
            f"{dxy_kpi.value:.2f}",
            delta=(
                f"{dxy_kpi.delta_pct:+.2f}%"
                if dxy_kpi.delta_pct is not None
                else None
            ),
        )
    else:
        cols[2].metric("DXY", "—")

    if snapshot.is_stale:
        st.caption(
            f"⚠️ Dati cache (etá: {snapshot.fetched_at_human}) — "
            "yfinance potrebbe essere temporaneamente non raggiungibile."
        )
    else:
        st.caption(
            f"📌 Fonte: yfinance · cache live ({snapshot.fetched_at_human})"
        )


if __name__ == "__main__":  # pragma: no cover
    render_page("Forex & Options", "💱", body_forex_options)
