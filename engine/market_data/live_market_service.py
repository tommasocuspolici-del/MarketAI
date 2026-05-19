"""LiveMarketService: facade KPI real-time con cache TTL e force refresh.

Estratto da 870 → 3 moduli (ROADMAP_CODE_QUALITY_v1.0, Settimana 7, P6):
  • kpi_computer.py   — dataclass, KpiComputer, download, utilities
  • delta_windows.py  — fetch_delta_windows
  • live_market_service.py (questo file) — LiveMarketService + singleton

Thread-safety:
  - _lock: protegge la cache (lettura/scrittura snapshot).
  - _refresh_cv: Condition per evitare N download HTTP paralleli.

Bugfix v7.1.1: race condition singleton + get_kpi_snapshot.
Bugfix v7.2.2: MultiIndex yfinance + fast_info fallback.
"""
from __future__ import annotations

import time
from threading import Condition, Lock
from typing import Any

from engine.market_data.delta_windows import fetch_delta_windows  # re-export
from engine.market_data.hardening.sanity_checker import SanityChecker
from engine.market_data.kpi_computer import (
    KpiComputer,
    MarketKpi,  # re-export
    MarketSnapshot,  # re-export
    DeltaWindow,  # re-export
    _KPI_DEFINITIONS,
    build_unavailable_kpis,
    download_market_data,
)
from engine.market_data.snapshot_disk_cache import SnapshotDiskCache
from personal.data_entry.override_store import ManualOverrideStore
from shared.config.operational_config import OP_CONFIG
from shared.logger import get_logger

__version__ = "9.1.0"

__all__ = [
    "DeltaWindow",
    "LiveMarketService",
    "MarketKpi",
    "MarketSnapshot",
    "fetch_delta_windows",
    "get_live_market_service",
]

log = get_logger(__name__)

_TTL_SECONDS: float = OP_CONFIG.cache.live_market_ttl_s
_DB_MAX_AGE_SECONDS = 6 * 3600
_DISK_MAX_AGE_SECONDS: float = OP_CONFIG.cache.disk_snapshot_max_age_s


class LiveMarketService:
    """Servizio singleton per fetch KPI real-time con cache e force refresh."""

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
        self._ws_manager: object | None = None
        self._disk_cache = SnapshotDiskCache(max_age_s=_DISK_MAX_AGE_SECONDS)
        self._kpi_computer = KpiComputer(
            override_store=self._override_store,
            sanity=self._sanity,
            get_ws_price_fn=self._get_ws_price,
            lookup_cached_fn=self._lookup_cached,
        )

    # ─── public api ─────────────────────────────────────────────────────────

    def get_kpi_snapshot(self, *, force: bool = False) -> MarketSnapshot:
        """Ritorna snapshot dei KPI. Usa cache se valida e non force=True."""
        with self._refresh_cv:
            cache_age = time.time() - self._cache.fetched_at
            if self._cache.kpis and cache_age < self._ttl and not force:
                return self._cache
            if self._refresh_in_progress:
                self._refresh_cv.wait_for(lambda: not self._refresh_in_progress, timeout=30.0)
                return self._cache
            self._refresh_in_progress = True

        new_snapshot = None
        try:
            new_snapshot = self._fetch_snapshot()
        except Exception as e:
            log.error("Failed to fetch snapshot", error=str(e))
            with self._lock:
                if self._cache.kpis:
                    new_snapshot = self._cache
                    new_snapshot.is_stale = True
                else:
                    _dc = getattr(self, "_disk_cache", None)
                    disk = _dc.load() if _dc is not None else None
                    if disk is not None:
                        new_snapshot = disk
                    else:
                        new_snapshot = MarketSnapshot(
                            kpis=build_unavailable_kpis(f"Fetch error: {e}")
                        )
        finally:
            with self._refresh_cv:
                self._cache = new_snapshot
                self._refresh_in_progress = False
                self._refresh_cv.notify_all()
        return new_snapshot

    def refresh_now(self) -> MarketSnapshot:
        """Forza un re-fetch immediato ignorando la cache."""
        return self.get_kpi_snapshot(force=True)

    def start_websocket_stream(self, tickers: list[str] | None = None) -> bool:
        """Avvia lo stream WebSocket Finnhub se il feature flag è abilitato."""
        try:
            from shared.feature_flags import is_enabled
            if not is_enabled("realtime_websocket"):
                return False
            from engine.market_data.websocket_manager import get_ws_manager
            ws = get_ws_manager()
            if ws is None:
                return False
            ws.start(tickers or [d[1] for d in _KPI_DEFINITIONS])
            self._ws_manager = ws
            log.info("live_market_service.ws_stream_started", tickers=len(tickers or _KPI_DEFINITIONS))
            return True
        except Exception as exc:
            log.warning("live_market_service.ws_start_failed", error=str(exc)[:120])
            return False

    def cache_age_seconds(self) -> float:
        with self._lock:
            return 0.0 if self._cache.fetched_at == 0 else time.time() - self._cache.fetched_at

    # ─── internals ──────────────────────────────────────────────────────────

    def _fetch_snapshot(self) -> MarketSnapshot:
        snapshot = MarketSnapshot()
        snapshot.fetched_at = time.time()

        try:
            import yfinance  # noqa: F401,PLC0415
        except ImportError:
            cached = self._read_cache_safe()
            if cached.kpis:
                cached.is_stale = True
                return cached
            _dc = getattr(self, "_disk_cache", None)
            disk = _dc.load() if _dc is not None else None
            if disk is not None:
                return disk
            snapshot.kpis = build_unavailable_kpis("yfinance non installato")
            snapshot.n_errors = len(snapshot.kpis)
            snapshot.is_unavailable = True
            return snapshot

        data = download_market_data([d[1] for d in _KPI_DEFINITIONS])
        if data is None or data.empty:
            cached = self._read_cache_safe()
            if cached.kpis:
                cached.is_stale = True
                return cached
            disk_cache = getattr(self, "_disk_cache", None)
            if disk_cache is not None:
                disk = disk_cache.load()
                if disk is not None:
                    return disk
            snapshot.kpis = build_unavailable_kpis("yfinance download failed")
            snapshot.n_errors = len(snapshot.kpis)
            snapshot.is_unavailable = True
            return snapshot

        for term, yf_ticker, currency, fmt in _KPI_DEFINITIONS:
            kpi = self._kpi_computer.extract_kpi(
                data=data, term=term, yf_ticker=yf_ticker, currency=currency, fmt=fmt,
            )
            snapshot.kpis.append(kpi)
            if kpi.error:
                snapshot.n_errors += 1

        _dc = getattr(self, "_disk_cache", None)
        if _dc is not None:
            _dc.save(snapshot)
        return snapshot

    def _extract_kpi(self, *, data: Any, term: str, yf_ticker: str, currency: str, fmt: str) -> MarketKpi:
        """Delegate to KpiComputer (backward compat — used by tests)."""
        return self._kpi_computer.extract_kpi(
            data=data, term=term, yf_ticker=yf_ticker, currency=currency, fmt=fmt,
        )

    def _get_ws_price(self, yf_ticker: str) -> float | None:
        if self._ws_manager is None:
            return None
        try:
            lp = self._ws_manager.get_price(yf_ticker)  # type: ignore[attr-defined]
            if lp is not None:
                return lp.price
        except Exception as exc:  # noqa: BLE001
            log.debug("live_market_service._get_ws_price: %s: %s", yf_ticker, type(exc).__name__)
        return None

    def _read_cache_safe(self) -> MarketSnapshot:
        with self._lock:
            return MarketSnapshot(
                kpis=list(self._cache.kpis),
                fetched_at=self._cache.fetched_at,
                is_stale=self._cache.is_stale,
                n_errors=self._cache.n_errors,
            )

    def _lookup_cached(self, term: str) -> MarketKpi | None:
        with self._lock:
            for k in self._cache.kpis:
                if k.term == term and k.value is not None:
                    return k
        return None


# ─── singleton ──────────────────────────────────────────────────────────────
_singleton_lock = Lock()
_singleton_instance: LiveMarketService | None = None


def get_live_market_service() -> LiveMarketService:
    """Lazy singleton thread-safe (double-checked locking)."""
    global _singleton_instance  # noqa: PLW0603
    if _singleton_instance is not None:
        return _singleton_instance
    with _singleton_lock:
        if _singleton_instance is None:
            _singleton_instance = LiveMarketService()
        return _singleton_instance


def _reset_singleton_for_testing() -> None:
    """Resetta il singleton — uso ESCLUSIVO nei test."""
    global _singleton_instance  # noqa: PLW0603
    with _singleton_lock:
        _singleton_instance = None
