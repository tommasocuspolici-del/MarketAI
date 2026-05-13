"""Yahoo Finance fetcher.

Wraps the synchronous ``yfinance`` library inside an asyncio thread to honor
Rule 11 (network calls must be awaitable from coroutine contexts). yfinance
is the only OHLCV provider that is fully open and free, so we use it as the
primary source. Rate limit configured under ``yahoo_finance`` in
``config/rate_limits.yaml``.

Notes:
  · yfinance does not expose an async API as of 0.2.x — wrapping in
    ``asyncio.to_thread`` is the canonical approach (no extra deps).
  · Yahoo's unofficial endpoints occasionally rate-limit aggressively;
    keep the configured RPM conservative and rely on diskcache.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pandas as pd

from engine.market_data.fetchers.base_fetcher import BaseOhlcvFetcher
from shared.exceptions import FetchError
from shared.logger import get_logger
from shared.types import DataSource, TimeFrame, ensure_utc

if TYPE_CHECKING:
    from datetime import datetime

    from engine.market_data.cleaning import DataCleaner
    from shared.db.dual_writer import DualWriter
    from shared.db.quality import QualityReportRepository
    from shared.rate_limit_manager import RateLimitManager

__version__ = "6.0.1"

__all__ = ["YahooFetcher"]

log = get_logger(__name__)


# Mapping TimeFrame → stringa interval accettata da yfinance
_INTERVAL_MAP: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "60m",        # yfinance usa "60m" non "1h"
    "4h": "60m",        # yfinance non supporta 4h: down-sample lato cliente
    "1d": "1d",
    "1w": "1wk",
    "1mo": "1mo",
}


class YahooFetcher(BaseOhlcvFetcher):
    """Primary OHLCV fetcher backed by yfinance.

    Subclasses should not need to override anything here. Just instantiate
    and call ``fetch(...)`` — the BaseOhlcvFetcher pipeline handles cleaning,
    validation, persistence, and quality reporting.
    """

    def __init__(
        self,
        rate_limiter: RateLimitManager | None = None,
        cleaner: DataCleaner | None = None,
        dual_writer: DualWriter | None = None,
        quality_repo: QualityReportRepository | None = None,
    ) -> None:
        super().__init__(
            source=DataSource.YAHOO_FINANCE,
            rate_limiter=rate_limiter,
            cleaner=cleaner,
            dual_writer=dual_writer,
            quality_repo=quality_repo,
        )

    async def _fetch_raw_ohlcv(
        self,
        ticker: str,
        exchange: str,
        timeframe: TimeFrame,
        start: datetime | None,
        end: datetime | None,
    ) -> pd.DataFrame:
        """Pull raw OHLCV bars from Yahoo. No cleaning here — that is BaseFetcher's job."""
        tf_str = timeframe.value if isinstance(timeframe, TimeFrame) else str(timeframe)
        interval = _INTERVAL_MAP.get(tf_str, "1d")

        # yfinance è sincrono → lo spostiamo su thread per non bloccare l'event loop
        try:
            raw = await asyncio.to_thread(
                self._download_sync, ticker, interval, start, end
            )
        except FetchError:
            raise
        except Exception as exc:
            # Errori di yfinance variano molto (HTTPError, KeyError, ValueError...)
            # Li normalizziamo in FetchError per uniformità con la pipeline base
            raise FetchError(
                source=self.source, detail=f"yfinance error for {ticker}: {exc}"
            ) from exc

        if raw is None or raw.empty:
            log.warning("yahoo.empty_response", ticker=ticker, interval=interval)
            return pd.DataFrame()

        return self._normalize_yahoo_frame(raw)

    @staticmethod
    def _download_sync(
        ticker: str,
        interval: str,
        start: datetime | None,
        end: datetime | None,
    ) -> pd.DataFrame | None:
        """Sync wrapper around yfinance.download — runs inside asyncio thread."""
        # Import locale: rende facoltativa la dipendenza yfinance per i test mock
        import yfinance as yf

        kwargs: dict[str, object] = {
            "tickers": ticker,
            "interval": interval,
            "auto_adjust": False,    # vogliamo close + adj_close separati
            "progress": False,
            "threads": False,         # già su un thread asyncio
            "group_by": "ticker",    # evita MultiIndex complicato
        }
        if start is not None:
            kwargs["start"] = ensure_utc(start).date().isoformat()
        if end is not None:
            kwargs["end"] = ensure_utc(end).date().isoformat()
        else:
            # Default yfinance: 1 mese se non specificato. Per OHLCV daily preferiamo
            # almeno 5 anni per garantire un'analisi tecnica significativa.
            kwargs["period"] = "5y" if start is None else None
            # Rimuove il period se start è specificato (mutuamente esclusivi)
            if kwargs["period"] is None:
                kwargs.pop("period")

        return yf.download(**kwargs)

    @staticmethod
    def _normalize_yahoo_frame(raw: pd.DataFrame) -> pd.DataFrame:
        """Convert yfinance output to our canonical OHLCV schema.

        yfinance returns:
          · single-level columns: ['Open','High','Low','Close','Adj Close','Volume']
          · OR multi-level if multiple tickers (we always use single ticker here)
          · Index is ``DatetimeIndex`` (often tz-naive in 'America/New_York')
        """
        # Se yfinance restituisce multi-index (multi-ticker) e noi abbiamo usato
        # group_by='ticker', la struttura è: (ticker, field). Prendiamo solo il ticker.
        if isinstance(raw.columns, pd.MultiIndex):
            # Prendiamo il primo ticker (dovrebbe essere l'unico)
            first_ticker = raw.columns.get_level_values(0)[0]
            raw = raw[first_ticker].copy()

        # Reset index: il timestamp diventa colonna ts.
        # Quando il DatetimeIndex non ha .name (default), reset_index() produce
        # una colonna chiamata "index". yfinance recente nomina sempre l'indice
        # "Date" o "Datetime", ma proteggiamo entrambi i casi per robustezza.
        df = raw.reset_index()

        # yfinance può usare "Date" / "Datetime" / "index" come colonna timestamp
        ts_col = next(
            (c for c in df.columns if c in ("Date", "Datetime", "index")), None
        )
        if ts_col is None:
            raise FetchError(
                source="yahoo_finance",
                detail=f"no timestamp column found in yfinance output: {list(df.columns)}",
            )

        # Force UTC tz-aware (Regola 19)
        ts_series = pd.to_datetime(df[ts_col])
        if ts_series.dt.tz is None:
            ts_series = ts_series.dt.tz_localize("UTC")
        else:
            ts_series = ts_series.dt.tz_convert("UTC")

        # Mappatura colonne: Yahoo → schema canonico
        rename_map = {
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
        }
        df = df.rename(columns=rename_map)
        df["ts"] = ts_series

        # Tipizzazione esplicita per evitare dtype "object" (Regola 9)
        for col in ("open", "high", "low", "close", "adj_close"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
        if "volume" in df.columns:
            # Yahoo ritorna float per volume → cast a int64 (lo schema richiede int)
            df["volume"] = (
                pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")
            )

        # Selezione colonne canoniche, scarta tutto il resto
        keep = ["ts", "open", "high", "low", "close", "volume", "adj_close"]
        df = df[[c for c in keep if c in df.columns]].copy()

        # Rimuove righe con tutti NaN nei prezzi (Yahoo le inserisce per festività)
        price_cols = [c for c in ("open", "high", "low", "close") if c in df.columns]
        if price_cols:
            df = df.dropna(subset=price_cols, how="all")

        return df.reset_index(drop=True)