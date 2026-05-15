"""Calcolo variazioni % multi-finestra per asset (1W/1M/YTD).

Estratto da live_market_service.py (ROADMAP_CODE_QUALITY_v1.0, Settimana 7, P6).
"""
from __future__ import annotations

from datetime import date

from engine.market_data.kpi_computer import DeltaWindow, _safe_float
from shared.logger import get_logger

log = get_logger(__name__)

_TRADING_DAYS_1W: int = 5
_TRADING_DAYS_1M: int = 21


def fetch_delta_windows(tickers: list[tuple[str, str]]) -> list[DeltaWindow]:
    """Calcola variazioni % 1W / 1M / YTD per N ticker via yfinance.

    Args:
        tickers: Lista di tuple (yahoo_ticker, label_display).

    Returns:
        Lista di DeltaWindow nello stesso ordine dei tickers in input.
        Errori di rete o ticker errati producono DeltaWindow con delta=None.
    """
    try:
        import yfinance as yf
    except ImportError:
        return [
            DeltaWindow(
                term=label, ticker=ticker,
                delta_1w=None, delta_1m=None, delta_ytd=None,
                error="yfinance non installato (poetry install)",
            )
            for ticker, label in tickers
        ]

    results: list[DeltaWindow] = []
    today = date.today()

    for ticker, label in tickers:
        try:
            import pandas as pd
            data = yf.download(
                tickers=ticker, period="1y", interval="1d",
                progress=False, auto_adjust=True, threads=False, group_by="column",
            )
        except (OSError, ValueError, KeyError) as exc:
            log.warning("delta_window.fetch_failed", ticker=ticker, error=str(exc))
            results.append(DeltaWindow(
                term=label, ticker=ticker,
                delta_1w=None, delta_1m=None, delta_ytd=None, error=str(exc),
            ))
            continue

        if data is None or data.empty:
            results.append(DeltaWindow(
                term=label, ticker=ticker,
                delta_1w=None, delta_1m=None, delta_ytd=None, error="Nessun dato yfinance",
            ))
            continue

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        close_col = next((c for c in data.columns if str(c).lower() == "close"), None)
        if close_col is None:
            results.append(DeltaWindow(
                term=label, ticker=ticker,
                delta_1w=None, delta_1m=None, delta_ytd=None, error="colonna Close mancante",
            ))
            continue

        close = data[close_col].dropna()
        if close.empty:
            results.append(DeltaWindow(
                term=label, ticker=ticker,
                delta_1w=None, delta_1m=None, delta_ytd=None, error="serie close vuota",
            ))
            continue

        last = _safe_float(close.iloc[-1])
        ref_1w = _safe_float(close.iloc[-_TRADING_DAYS_1W - 1]) if len(close) > _TRADING_DAYS_1W else None
        ref_1m = _safe_float(close.iloc[-_TRADING_DAYS_1M - 1]) if len(close) > _TRADING_DAYS_1M else None
        ref_ytd: float | None = None
        try:
            year_data = close[close.index.year == today.year]
            if not year_data.empty:
                ref_ytd = float(year_data.iloc[0])
        except (AttributeError, TypeError):
            pass

        def _pct(ref: float | None) -> float | None:
            return None if ref is None or ref == 0 else (last - ref) / ref

        results.append(DeltaWindow(
            term=label, ticker=ticker,
            delta_1w=_pct(ref_1w), delta_1m=_pct(ref_1m), delta_ytd=_pct(ref_ytd),
            last_price=last,
        ))

    return results
