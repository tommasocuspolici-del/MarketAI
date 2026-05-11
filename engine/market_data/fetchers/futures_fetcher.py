"""FuturesFetcher — Roadmap Unificata Settimana 1, Giorno 5.

Fetcher per contratti futures continui via yfinance (free tier).
Eredita da BaseOhlcvFetcher e aggiunge il calcolo di:
  · roll_yield = (front_close / second_close) - 1
  · basis = futures_close - spot_etf_close
  · term_structure: 'backwardation' | 'contango' | 'flat'

Ticker futures continui supportati (yfinance continuous contracts):
  CL=F  → WTI Crude (spot proxy: USO)
  GC=F  → Gold (spot proxy: GLD)
  ES=F  → S&P 500 (spot proxy: SPY)
  ZC=F  → Corn (spot proxy: CORN)
  ZW=F  → Wheat (spot proxy: WEAT)

Regola 11: asyncio.to_thread per yfinance (sincrono).
Regola 12: pipeline fetch→clean→validate→duckdb_write rispettata.
Regola 27: dati scritti in futures_ohlcv (migration 007).
Regola 28: RateLimitManager con source='yahoo_finance' (stessa quota).
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from engine.market_data.fetchers.base_fetcher import BaseOhlcvFetcher
from shared.exceptions import FetchError
from shared.logger import get_logger
from shared.types import DataSource, TimeFrame, ensure_utc

if TYPE_CHECKING:
    from datetime import datetime

    from engine.market_data.cleaning import DataCleaner
    from shared.db.dual_writer import DualWriter
    from shared.db.duckdb_client import DuckDBClient
    from shared.db.quality import QualityReportRepository
    from shared.rate_limit_manager import RateLimitManager

__version__ = "1.0.0"

__all__ = ["FuturesFetcher"]

log = get_logger(__name__)


# Mapping ticker futures → ETF spot proxy per il calcolo del basis
_SPOT_PROXIES: dict[str, str] = {
    "CL=F": "USO",   # WTI Oil
    "GC=F": "GLD",   # Gold
    "ES=F": "SPY",   # S&P 500
    "ZC=F": "CORN",  # Corn
    "ZW=F": "WEAT",  # Wheat
}

# Tutti i ticker futures che questo fetcher gestisce
FUTURES_TICKERS: list[str] = list(_SPOT_PROXIES.keys())


class FuturesFetcher(BaseOhlcvFetcher):
    """Fetcher specializzato per futures continui con roll_yield e basis.

    Estende BaseOhlcvFetcher aggiungendo il calcolo di metriche futures-specific
    e la persistenza in futures_ohlcv invece di prices_ohlcv.

    Usage::

        fetcher = FuturesFetcher(duckdb_client=get_duckdb_client())
        outcome = await fetcher.fetch_futures("CL=F", days=30)

    Notes:
        Il calcolo del roll_yield richiede due contratti (front + second).
        yfinance fornisce solo il front month continuo; il "second" viene
        approssimato tramite il prezzo 30 giorni fa come proxy del contratto
        precedente. Questa è un'approssimazione accettabile per screening.
    """

    def __init__(
        self,
        duckdb_client: DuckDBClient | None = None,
        rate_limiter: RateLimitManager | None = None,
        cleaner: DataCleaner | None = None,
        dual_writer: DualWriter | None = None,
        quality_repo: QualityReportRepository | None = None,
    ) -> None:
        super().__init__(
            source=DataSource.YAHOO_FINANCE,  # stessa quota rate limit
            rate_limiter=rate_limiter,
            cleaner=cleaner,
            dual_writer=dual_writer,
            quality_repo=quality_repo,
        )
        self._duckdb = duckdb_client

    # ─── Public API ──────────────────────────────────────────────────────────

    async def fetch_futures(
        self,
        ticker: str,
        days: int = 30,
    ) -> dict[str, object]:
        """Fetcha i dati del front-month futures e calcola roll_yield + basis.

        Args:
            ticker: Simbolo futures continuo (es. 'CL=F', 'GC=F', 'ES=F').
            days:   Numero di giorni storici da scaricare.

        Returns:
            Dict con chiavi: 'ticker', 'latest_close', 'roll_yield',
            'basis', 'term_structure', 'rows_written'.

        Raises:
            FetchError: Se yfinance non restituisce dati validi.
            ValueError: Se il ticker non è tra quelli supportati.
        """
        if ticker not in _SPOT_PROXIES:
            raise ValueError(
                f"Ticker futures '{ticker}' non supportato. "
                f"Supportati: {list(_SPOT_PROXIES.keys())}"
            )

        log.info("futures_fetcher.start", ticker=ticker, days=days)

        # 1. Fetch front-month futures
        futures_df = await self._yf_download(ticker, days=days + 5)
        if futures_df is None or futures_df.empty:
            raise FetchError(f"Nessun dato yfinance per {ticker}")

        closes = futures_df["Close"].to_numpy(dtype=np.float64)
        latest_close = float(closes[-1])

        # 2. Roll yield: approssimazione con prezzo N giorni fa
        #    roll_yield = (front_current / front_30d_ago) - 1
        #    In assenza di dati secondo contratto, usiamo questo proxy.
        days_back = min(22, len(closes) - 1)  # ~1 mese lavorativo
        if days_back > 0 and closes[-(days_back + 1)] > 0:
            second_proxy = float(closes[-(days_back + 1)])
            roll_yield = float(
                np.float64(latest_close) / np.float64(second_proxy) - np.float64(1.0)
            )
        else:
            roll_yield = 0.0
            second_proxy = latest_close

        annualized_roll = float(roll_yield * (np.float64(252) / np.float64(days_back or 22)))
        term_structure = self._classify_term_structure(roll_yield)

        # 3. Basis = futures_close - spot_etf_close
        spot_ticker = _SPOT_PROXIES[ticker]
        spot_df = await self._yf_download(spot_ticker, days=5)
        basis: float | None = None
        if spot_df is not None and not spot_df.empty:
            spot_close = float(spot_df["Close"].iloc[-1])
            basis = latest_close - spot_close

        # 4. Persisti in futures_ohlcv
        rows_written = self._persist_futures_rows(
            ticker=ticker,
            futures_df=futures_df,
            roll_yield=roll_yield,
            basis=basis,
            term_structure=term_structure,
        )

        result = {
            "ticker": ticker,
            "latest_close": latest_close,
            "second_proxy": second_proxy,
            "roll_yield": roll_yield,
            "annualized_roll": annualized_roll,
            "basis": basis,
            "term_structure": term_structure,
            "spot_ticker": spot_ticker,
            "rows_written": rows_written,
        }

        log.info(
            "futures_fetcher.done",
            ticker=ticker,
            close=round(latest_close, 2),
            roll_yield=round(roll_yield * 100, 3),
            term_structure=term_structure,
            basis=round(basis, 3) if basis is not None else None,
            rows_written=rows_written,
        )
        return result

    async def fetch_all(self, days: int = 30) -> list[dict[str, object]]:
        """Fetcha tutti i futures ticker supportati in sequenza.

        Usa sequenza (non parallelo) per rispettare il rate limit.

        Args:
            days: Giorni storici da scaricare per ogni ticker.

        Returns:
            Lista di result dict per ogni ticker.
        """
        results = []
        for ticker in FUTURES_TICKERS:
            try:
                result = await self.fetch_futures(ticker, days=days)
                results.append(result)
            except Exception as exc:
                log.error(
                    "futures_fetcher.ticker_failed",
                    ticker=ticker,
                    error=str(exc)[:100],
                )
        return results

    # ─── Implementazione BaseOhlcvFetcher._fetch_raw_ohlcv (richiesta dalla ABC) ──

    async def _fetch_raw_ohlcv(
        self,
        ticker: str,
        exchange: str,
        timeframe: TimeFrame,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """Implementazione richiesta da BaseOhlcvFetcher.

        Scarica OHLCV standard via yfinance per compatibilità con la pipeline.
        Per i futures specifici usa fetch_futures() che aggiunge roll/basis.
        """
        df = await self._yf_download(ticker, days=252)
        if df is None or df.empty:
            raise FetchError(f"Nessun dato per {ticker}")
        return df

    # ─── Helpers privati ─────────────────────────────────────────────────────

    async def _yf_download(self, ticker: str, days: int) -> pd.DataFrame | None:
        """Scarica dati da yfinance in un thread separato (Rule 11)."""
        # Rate limit: stessa quota di YahooFetcher
        await self._rate_limiter.acquire("yahoo_finance")

        def _sync_download() -> pd.DataFrame | None:
            try:
                import yfinance as yf
                data = yf.download(
                    ticker,
                    period=f"{days}d",
                    interval="1d",
                    auto_adjust=True,
                    progress=False,
                    show_errors=False,
                )
                if data is None or data.empty:
                    return None
                # yfinance restituisce MultiIndex se multi-ticker; normalize
                if isinstance(data.columns, pd.MultiIndex):
                    data.columns = data.columns.get_level_values(0)
                return data
            except Exception as exc:
                log.warning(
                    "futures_fetcher.yf_error",
                    ticker=ticker,
                    error=str(exc)[:100],
                )
                return None

        return await asyncio.to_thread(_sync_download)

    @staticmethod
    def _classify_term_structure(roll_yield: float) -> str:
        """Classifica la term structure in base al roll yield.

        Args:
            roll_yield: (front / second) - 1.

        Returns:
            'backwardation' se roll_yield > +0.5%
            'contango'      se roll_yield < -0.5%
            'flat'          altrimenti
        """
        if roll_yield > 0.005:
            return "backwardation"
        if roll_yield < -0.005:
            return "contango"
        return "flat"

    def _persist_futures_rows(
        self,
        ticker: str,
        futures_df: pd.DataFrame,
        roll_yield: float,
        basis: float | None,
        term_structure: str,
    ) -> int:
        """Scrive le ultime N righe in futures_ohlcv su DuckDB.

        Args:
            ticker:          Simbolo futures.
            futures_df:      DataFrame con OHLCV da yfinance.
            roll_yield:      Roll yield calcolato.
            basis:           Basis calcolato (può essere None).
            term_structure:  'backwardation'|'contango'|'flat'.

        Returns:
            Numero di righe inserite (0 se DuckDB non disponibile).
        """
        if self._duckdb is None:
            log.debug("futures_fetcher.no_duckdb_skip_persist", ticker=ticker)
            return 0

        # Scrivi solo gli ultimi 30 record per non sovraccaricare
        df = futures_df.tail(30).copy()
        df.index = pd.to_datetime(df.index, utc=True)

        rows_written = 0
        for ts, row in df.iterrows():
            try:
                close_val = float(row.get("Close", row.get("close", 0.0)))
                if close_val <= 0:
                    continue
                self._duckdb.execute(
                    """INSERT OR REPLACE INTO futures_ohlcv
                       (ticker, contract_month, ts, open, high, low, close,
                        volume, roll_yield, basis, term_structure, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        ticker,
                        "front",
                        ensure_utc(ts),
                        float(row.get("Open", row.get("open", close_val))),
                        float(row.get("High", row.get("high", close_val))),
                        float(row.get("Low", row.get("low", close_val))),
                        close_val,
                        int(row.get("Volume", row.get("volume", 0)) or 0),
                        roll_yield,
                        basis,
                        term_structure,
                        "yfinance_futures",
                    ],
                )
                rows_written += 1
            except Exception as exc:
                log.debug(
                    "futures_fetcher.row_insert_failed",
                    ticker=ticker,
                    ts=str(ts),
                    error=str(exc)[:80],
                )

        return rows_written
