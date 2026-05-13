"""LiveMarketService: dati di mercato real-time con cache TTL e force refresh.

Risolve i problemi di connessione a Yahoo Finance con fallback granulare.
"""
from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from datetime import date
from threading import Condition, Lock
from typing import Any

import pandas as pd

from engine.market_data.hardening.sanity_checker import SanityChecker
from engine.market_data.hardening.silent_failure_detector import (
    SilentFailureError,
)
from personal.data_entry.override_store import ManualOverrideStore
from shared.logger import get_logger

__version__ = "7.2.2"

__all__ = [
    "DeltaWindow",
    "LiveMarketService",
    "MarketKpi",
    "MarketSnapshot",
    "fetch_delta_windows",
    "get_live_market_service",
]

log = get_logger(__name__)

_TTL_SECONDS = 60.0

_KPI_DEFINITIONS: list[tuple[str, str, str, str]] = [
    ("S&P 500",   "^GSPC",  "USD", ",.2f"),
    ("NASDAQ",    "^IXIC",  "USD", ",.2f"),
    ("DJIA",      "^DJI",   "USD", ",.2f"),
    ("FTSE MIB",  "FTSEMIB.MI", "EUR", ",.2f"),
    ("VIX",       "^VIX",   "USD", ".2f"),
    ("DXY",       "DX-Y.NYB", "USD", ".2f"),
    ("EUR/USD",   "EURUSD=X", "USD", ".4f"),
    ("Gold",      "GC=F",   "USD", ",.2f"),
    ("WTI",       "CL=F",   "USD", ".2f"),
    ("Brent",     "BZ=F",   "USD", ".2f"),
    ("Silver",    "SI=F",   "USD", ".3f"),
    ("Nat Gas",   "NG=F",   "USD", ".3f"),
    ("Copper",    "HG=F",   "USD", ".3f"),
]


@dataclass(frozen=True, slots=True)
class MarketKpi:
    term: str
    yf_ticker: str
    value: float | None
    delta_pct: float | None
    currency: str
    format_spec: str
    is_override: bool = False
    is_stale: bool = False
    error: str = ""


@dataclass(frozen=True, slots=True)
class DeltaWindow:
    term: str
    ticker: str
    delta_1w: float | None
    delta_1m: float | None
    delta_ytd: float | None
    last_price: float | None = None
    error: str = ""


@dataclass(slots=True)
class MarketSnapshot:
    kpis: list[MarketKpi] = field(default_factory=list)
    fetched_at: float = 0.0
    is_stale: bool = False
    n_errors: int = 0

    @property
    def fetched_at_human(self) -> str:
        if self.fetched_at == 0:
            return "mai"
        delta = time.time() - self.fetched_at
        if delta < 60:
            return f"{int(delta)}s fa"
        if delta < 3600:
            return f"{int(delta / 60)}m fa"
        return f"{int(delta / 3600)}h fa"


class LiveMarketService:
    def __init__(
        self,
        *,
        override_store: ManualOverrideStore | None = None,
        sanity: SanityChecker | None = None,
        ttl_seconds: float = _TTL_SECONDS,
    ) -> None:
        self._override_store = override_store or ManualOverrideStore()
        self._sanity = sanity or SanityChecker()
        self._ttl = ttl_seconds
        self._cache: MarketSnapshot = MarketSnapshot()
        self._lock = Lock()
        self._refresh_cv = Condition(self._lock)
        self._refresh_in_progress = False

    def get_kpi_snapshot(self, *, force: bool = False) -> MarketSnapshot:
        with self._refresh_cv:
            cache_age = time.time() - self._cache.fetched_at
            cache_valid = (
                self._cache.kpis and cache_age < self._ttl and not force
            )
            if cache_valid:
                return self._cache

            if self._refresh_in_progress:
                self._refresh_cv.wait_for(
                    lambda: not self._refresh_in_progress, timeout=30.0
                )
                return self._cache

            self._refresh_in_progress = True

        new_snapshot = None
        try:
            new_snapshot = self._fetch_snapshot()
        except Exception as e:
            log.error(
                "Failed to fetch snapshot",
                error=str(e),
                traceback=traceback.format_exc(),
            )
            with self._lock:
                if self._cache.kpis:
                    new_snapshot = self._cache
                    new_snapshot.is_stale = True
                else:
                    new_snapshot = MarketSnapshot(
                        kpis=self._build_unavailable_kpis(f"Fetch error: {e}")
                    )
        finally:
            with self._refresh_cv:
                self._cache = new_snapshot
                self._refresh_in_progress = False
                self._refresh_cv.notify_all()

        return new_snapshot

    def refresh_now(self) -> MarketSnapshot:
        return self.get_kpi_snapshot(force=True)

    def cache_age_seconds(self) -> float:
        with self._lock:
            if self._cache.fetched_at == 0:
                return 0.0
            return time.time() - self._cache.fetched_at

    # -------------------------------------------------------------
    def _fetch_snapshot(self) -> MarketSnapshot:
        snapshot = MarketSnapshot()
        snapshot.fetched_at = time.time()

        try:
            import yfinance as yf
        except ImportError:
            cached = self._read_cache_safe()
            if cached.kpis:
                cached.is_stale = True
                return cached
            snapshot.kpis = self._build_unavailable_kpis("yfinance non installato")
            snapshot.n_errors = len(snapshot.kpis)
            return snapshot

        tickers_list = [d[1] for d in _KPI_DEFINITIONS]
        data = None
        bulk_ok = False

        # Tentativo 1: download bulk con group_by='ticker'
        try:
            log.info("Bulk download starting", tickers=tickers_list)
            data = yf.download(
                tickers=tickers_list,
                period="5d",
                interval="1d",
                progress=False,
                auto_adjust=True,
                group_by='ticker',
            )
            if data is not None and not data.empty:
                bulk_ok = True
                log.info("Bulk download succeeded", shape=data.shape)
            else:
                log.warning("Bulk download returned empty data")
        except Exception as exc:
            log.warning(
                "Bulk download failed",
                error=str(exc),
                tickers=tickers_list,
            )
            data = None

        # Se bulk fallisce, tentativo 2: download ticker per ticker
        if not bulk_ok:
            log.info("Falling back to per-ticker download")
            data = {}
            for term, yf_ticker, _, _ in _KPI_DEFINITIONS:
                try:
                    single = yf.download(
                        tickers=yf_ticker,
                        period="5d",
                        interval="1d",
                        progress=False,
                        auto_adjust=True,
                    )
                    if single is not None and not single.empty:
                        data[yf_ticker] = single
                    else:
                        log.warning("No data for ticker", ticker=yf_ticker)
                except Exception as exc:
                    log.error("Ticker download failed", ticker=yf_ticker, error=str(exc))
            if not data:
                cached = self._read_cache_safe()
                if cached.kpis:
                    cached.is_stale = True
                    return cached
                snapshot.kpis = self._build_unavailable_kpis("All downloads failed")
                snapshot.n_errors = len(snapshot.kpis)
                return snapshot

        # Elaborazione KPI
        for term, yf_ticker, currency, fmt in _KPI_DEFINITIONS:
            kpi = self._extract_kpi(
                data=data,
                term=term,
                yf_ticker=yf_ticker,
                currency=currency,
                fmt=fmt,
                bulk_mode=bulk_ok,
            )
            snapshot.kpis.append(kpi)
            if kpi.error:
                snapshot.n_errors += 1

        return snapshot

    def _get_ticker_frame(self, data: Any, yf_ticker: str, bulk_mode: bool) -> Any:
        """Estrae il DataFrame per un ticker sia da bulk che da per-ticker."""
        if data is None:
            return None

        if bulk_mode:
            # Caso bulk con group_by='ticker'
            if yf_ticker in data.columns.get_level_values(0):
                return data[yf_ticker].copy()
        else:
            # Caso per-ticker: data è un dict {ticker: DataFrame}
            return data.get(yf_ticker)

        return None

    def _fetch_fast_info_fallback(self, yf_ticker: str) -> tuple[float | None, float | None]:
        try:
            import yfinance as yf
            t = yf.Ticker(yf_ticker)
            fi = t.fast_info
            price = getattr(fi, "last_price", None)
            prev = getattr(fi, "previous_close", None)
            if price is None or price != price:
                return None, None
            price_f = float(price)
            delta = None
            if prev is not None and float(prev) > 0:
                delta = (price_f - float(prev)) / float(prev)
            return price_f, delta
        except Exception as e:
            log.debug("fast_info fallback failed", ticker=yf_ticker, error=str(e))
            return None, None

    def _read_cache_safe(self) -> MarketSnapshot:
        with self._lock:
            return MarketSnapshot(
                kpis=list(self._cache.kpis),
                fetched_at=self._cache.fetched_at,
                is_stale=self._cache.is_stale,
                n_errors=self._cache.n_errors,
            )

    def _extract_kpi(
        self,
        *,
        data: Any,
        term: str,
        yf_ticker: str,
        currency: str,
        fmt: str,
        bulk_mode: bool,
    ) -> MarketKpi:
        try:
            ticker_data = self._get_ticker_frame(data, yf_ticker, bulk_mode)
            if ticker_data is None or ticker_data.empty:
                raise SilentFailureError("yfinance", f"empty data for {yf_ticker}")

            ticker_data = ticker_data.dropna(how="all")
            if ticker_data.empty or len(ticker_data) < 1:
                raise SilentFailureError("yfinance", f"no rows for {yf_ticker}")

            close_col = "Close" if "Close" in ticker_data.columns else "close"
            if close_col not in ticker_data.columns:
                raise SilentFailureError("yfinance", f"no Close column for {yf_ticker}")

            last_close = float(ticker_data[close_col].iloc[-1])
            prev_close = (
                float(ticker_data[close_col].iloc[-2])
                if len(ticker_data) >= 2
                else last_close
            )

            violations = self._sanity.check_price_data(
                yf_ticker, last_close, prev_close=prev_close
            )
            if not self._sanity.is_safe_to_store(violations):
                cached = self._lookup_cached(term)
                if cached is not None:
                    return MarketKpi(
                        term=term,
                        yf_ticker=yf_ticker,
                        value=cached.value,
                        delta_pct=cached.delta_pct,
                        currency=cached.currency,
                        format_spec=fmt,
                        is_stale=True,
                        error="sanity violation, using last good value",
                    )

            api_delta_pct = None
            if prev_close > 0:
                api_delta_pct = (last_close - prev_close) / prev_close

            final_value, is_override = self._override_store.resolve(
                "price", term, last_close
            )

            return MarketKpi(
                term=term,
                yf_ticker=yf_ticker,
                value=final_value,
                delta_pct=api_delta_pct,
                currency=currency,
                format_spec=fmt,
                is_override=is_override,
            )

        except SilentFailureError as exc:
            price_fb, delta_fb = self._fetch_fast_info_fallback(yf_ticker)
            if price_fb is not None:
                log.info("fast_info_fallback_used", ticker=yf_ticker)
                return MarketKpi(
                    term=term,
                    yf_ticker=yf_ticker,
                    value=price_fb,
                    delta_pct=delta_fb,
                    currency=currency,
                    format_spec=fmt,
                )
            cached = self._lookup_cached(term)
            if cached is not None:
                return MarketKpi(
                    term=term,
                    yf_ticker=yf_ticker,
                    value=cached.value,
                    delta_pct=cached.delta_pct,
                    currency=cached.currency,
                    format_spec=fmt,
                    is_stale=True,
                    error=f"silent_failure: {exc.reason[:80]}",
                )
            return MarketKpi(
                term=term,
                yf_ticker=yf_ticker,
                value=None,
                delta_pct=None,
                currency=currency,
                format_spec=fmt,
                error=f"silent_failure: {exc.reason[:80]}",
            )
        except (KeyError, ValueError, IndexError, AttributeError) as exc:
            cached = self._lookup_cached(term)
            if cached is not None:
                return MarketKpi(
                    term=term,
                    yf_ticker=yf_ticker,
                    value=cached.value,
                    delta_pct=cached.delta_pct,
                    currency=cached.currency,
                    format_spec=fmt,
                    is_stale=True,
                    error=f"parse_error: {str(exc)[:80]}",
                )
            return MarketKpi(
                term=term,
                yf_ticker=yf_ticker,
                value=None,
                delta_pct=None,
                currency=currency,
                format_spec=fmt,
                error=f"parse_error: {str(exc)[:80]}",
            )

    def _lookup_cached(self, term: str) -> MarketKpi | None:
        with self._lock:
            for k in self._cache.kpis:
                if k.term == term and k.value is not None:
                    return k
        return None

    @staticmethod
    def _build_unavailable_kpis(reason: str) -> list[MarketKpi]:
        return [
            MarketKpi(
                term=term,
                yf_ticker=yf_ticker,
                value=None,
                delta_pct=None,
                currency=currency,
                format_spec=fmt,
                error=reason,
            )
            for term, yf_ticker, currency, fmt in _KPI_DEFINITIONS
        ]


_singleton_lock = Lock()
_singleton_instance: LiveMarketService | None = None


def get_live_market_service() -> LiveMarketService:
    global _singleton_instance
    if _singleton_instance is not None:
        return _singleton_instance
    with _singleton_lock:
        if _singleton_instance is None:
            _singleton_instance = LiveMarketService()
        return _singleton_instance


def _reset_singleton_for_testing() -> None:
    global _singleton_instance
    with _singleton_lock:
        _singleton_instance = None


_TRADING_DAYS_1W: int = 5
_TRADING_DAYS_1M: int = 21


def fetch_delta_windows(tickers: list[tuple[str, str]]) -> list[DeltaWindow]:
    try:
        import yfinance as yf
    except ImportError:
        return [
            DeltaWindow(
                term=label,
                ticker=ticker,
                delta_1w=None,
                delta_1m=None,
                delta_ytd=None,
                error="yfinance non installato",
            )
            for ticker, label in tickers
        ]

    results = []
    today = date.today()
    for ticker, label in tickers:
        try:
            data = yf.download(
                tickers=ticker,
                period="1y",
                interval="1d",
                progress=False,
                auto_adjust=True,
                threads=False,
            )
        except Exception as exc:
            results.append(
                DeltaWindow(
                    term=label, ticker=ticker,
                    delta_1w=None, delta_1m=None, delta_ytd=None,
                    error=str(exc),
                )
            )
            continue

        if data is None or data.empty:
            results.append(
                DeltaWindow(
                    term=label, ticker=ticker,
                    delta_1w=None, delta_1m=None, delta_ytd=None,
                    error="Nessun dato",
                )
            )
            continue

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        close_col = next((col for col in data.columns if str(col).lower() == "close"), None)
        if close_col is None:
            results.append(
                DeltaWindow(
                    term=label, ticker=ticker,
                    delta_1w=None, delta_1m=None, delta_ytd=None,
                    error="colonna Close mancante",
                )
            )
            continue

        close = data[close_col].dropna()
        if close.empty:
            results.append(
                DeltaWindow(
                    term=label, ticker=ticker,
                    delta_1w=None, delta_1m=None, delta_ytd=None,
                    error="serie close vuota",
                )
            )
            continue

        last = float(close.iloc[-1])
        ref_1w = float(close.iloc[-_TRADING_DAYS_1W - 1]) if len(close) > _TRADING_DAYS_1W else None
        ref_1m = float(close.iloc[-_TRADING_DAYS_1M - 1]) if len(close) > _TRADING_DAYS_1M else None
        ref_ytd = None
        try:
            year_mask = close.index.year == today.year
            year_data = close[year_mask]
            if not year_data.empty:
                ref_ytd = float(year_data.iloc[0])
        except Exception:
            pass

        def _pct(ref):
            return (last - ref) / ref if ref and ref != 0 else None

        results.append(
            DeltaWindow(
                term=label,
                ticker=ticker,
                delta_1w=_pct(ref_1w),
                delta_1m=_pct(ref_1m),
                delta_ytd=_pct(ref_ytd),
                last_price=last,
            )
        )
    return results