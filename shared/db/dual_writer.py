"""Dual writer — coordinates DuckDB bulk writes with L1 cache (Rule 12).

The sacred pipeline (Rule 12):
    fetch → clean → validate → **duckdb_write → cache** → return

This module owns the last two steps. Callers provide already-cleaned,
already-validated DataFrames. The dual writer:

  1. Persists to DuckDB via the appropriate repository (idempotent upsert).
  2. Updates the L1 cache (diskcache) with a configurable TTL.
  3. Returns the rows written count — callers decide how to use it.

The L1 cache speeds up hot reads (single ticker, recent window) without
hitting DuckDB every time. Invalidation on writes is automatic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pandas as pd

from shared.constants import CACHE_TTL_MACRO, CACHE_TTL_PRICES, DATA_DIR
from shared.db.macro_repo import MacroRepository, get_macro_repository
from shared.db.prices_repo import PricesRepository, get_prices_repository
from shared.exceptions import DataError
from shared.logger import get_logger
from shared.metrics import metrics
from shared.types import TimeFrame

if TYPE_CHECKING:
    from pathlib import Path

__version__ = "6.0.0"

__all__ = ["DualWriteResult", "DualWriter", "get_dual_writer"]

log = get_logger(__name__)

_DEFAULT_CACHE_DIR: Path = DATA_DIR / "cache"
_DEFAULT_CACHE_SIZE_MB: int = 1024


@dataclass(frozen=True, slots=True)
class DualWriteResult:
    """Outcome of a dual-write operation."""

    rows_written: int
    cached: bool
    cache_key: str | None = None


class _NullCache:
    """Fallback cache that silently accepts writes when diskcache is unavailable.

    Keeps the DualWriter usable in environments without diskcache installed
    (dev, CI). Cache operations become no-ops; DuckDB writes still happen.
    """

    def set(self, key: str, value: Any, expire: int | None = None) -> bool:
        return False

    def get(self, key: str, default: Any = None) -> Any:
        return default

    def delete(self, key: str) -> int:
        return 0

    def close(self) -> None:
        return None


def _open_cache(cache_dir: Path, size_limit_bytes: int) -> Any:
    """Open a diskcache Cache if available; otherwise return a _NullCache."""
    try:
        # Import locale per non forzare diskcache come dipendenza dura dei test
        import diskcache

        cache_dir.mkdir(parents=True, exist_ok=True)
        return diskcache.Cache(str(cache_dir), size_limit=size_limit_bytes)
    except ImportError:
        log.warning("dual_writer.diskcache_unavailable")
        return _NullCache()


class DualWriter:
    """Coordinator for the DuckDB + cache write pipeline (Rule 12).

    Normally accessed via ``get_dual_writer()``. Accepts pre-validated
    DataFrames — validation (Pandera) happens inside the repositories.
    """

    def __init__(
        self,
        prices_repo: PricesRepository | None = None,
        macro_repo: MacroRepository | None = None,
        cache_dir: Path | None = None,
        cache_size_mb: int = _DEFAULT_CACHE_SIZE_MB,
    ) -> None:
        self._prices = prices_repo or get_prices_repository()
        self._macro = macro_repo or get_macro_repository()

        resolved_cache_dir = cache_dir or _DEFAULT_CACHE_DIR
        self._cache = _open_cache(resolved_cache_dir, cache_size_mb * 1_048_576)
        self._cache_dir = resolved_cache_dir

    # ─── Prices pipeline (Rule 12 final two steps) ──────────────────────
    def write_prices(
        self,
        ticker: str,
        exchange: str,
        timeframe: TimeFrame | str,
        df: pd.DataFrame,
        source: str,
        currency: str = "USD",
        cache_ttl: int = CACHE_TTL_PRICES,
    ) -> DualWriteResult:
        """Persist OHLCV + update L1 cache.

        The DataFrame MUST already be cleaned (DataCleaner) and conform
        to OHLCV_SCHEMA — repositories revalidate defensively.
        """
        if df.empty:
            return DualWriteResult(rows_written=0, cached=False)

        tf_str = timeframe.value if isinstance(timeframe, TimeFrame) else timeframe

        # 1. DuckDB write (idempotent upsert)
        n = self._prices.write_ohlcv(
            ticker=ticker,
            exchange=exchange,
            timeframe=tf_str,
            df=df,
            source=source,
            currency=currency,
        )

        # 2. Cache update with a deterministic key
        cache_key = self._build_prices_cache_key(ticker, exchange, tf_str)
        cached_ok = self._safe_cache_set(cache_key, df, ttl=cache_ttl)

        metrics.inc("dual_writer_prices_total", source=source)
        return DualWriteResult(rows_written=n, cached=cached_ok, cache_key=cache_key)

    def read_cached_prices(
        self,
        ticker: str,
        exchange: str,
        timeframe: TimeFrame | str,
    ) -> pd.DataFrame | None:
        """Return cached prices DataFrame or None on miss / cache disabled."""
        tf_str = timeframe.value if isinstance(timeframe, TimeFrame) else timeframe
        key = self._build_prices_cache_key(ticker, exchange, tf_str)
        value = self._safe_cache_get(key)
        if value is None:
            metrics.inc("cache_misses_total", namespace="prices")
            return None
        metrics.inc("cache_hits_total", namespace="prices")
        return value if isinstance(value, pd.DataFrame) else None

    # ─── Macro pipeline ─────────────────────────────────────────────────
    def write_macro(
        self,
        series_id: str,
        df: pd.DataFrame,
        source: str,
        unit: str | None = None,
        frequency: str | None = None,
        cache_ttl: int = CACHE_TTL_MACRO,
    ) -> DualWriteResult:
        """Persist macro series + update L1 cache."""
        if df.empty:
            return DualWriteResult(rows_written=0, cached=False)

        n = self._macro.write_macro_series(
            series_id=series_id,
            df=df,
            source=source,
            unit=unit,
            frequency=frequency,
        )

        cache_key = self._build_macro_cache_key(series_id)
        cached_ok = self._safe_cache_set(cache_key, df, ttl=cache_ttl)

        metrics.inc("dual_writer_macro_total", source=source)
        return DualWriteResult(rows_written=n, cached=cached_ok, cache_key=cache_key)

    def read_cached_macro(self, series_id: str) -> pd.DataFrame | None:
        """Return cached macro series or None on miss."""
        key = self._build_macro_cache_key(series_id)
        value = self._safe_cache_get(key)
        if value is None:
            metrics.inc("cache_misses_total", namespace="macro")
            return None
        metrics.inc("cache_hits_total", namespace="macro")
        return value if isinstance(value, pd.DataFrame) else None

    # ─── Cache management ───────────────────────────────────────────────
    def invalidate_prices(
        self,
        ticker: str,
        exchange: str,
        timeframe: TimeFrame | str,
    ) -> bool:
        """Evict a specific prices entry from L1 cache."""
        tf_str = timeframe.value if isinstance(timeframe, TimeFrame) else timeframe
        key = self._build_prices_cache_key(ticker, exchange, tf_str)
        return self._safe_cache_delete(key) > 0

    def invalidate_macro(self, series_id: str) -> bool:
        """Evict a macro series from L1 cache."""
        key = self._build_macro_cache_key(series_id)
        return self._safe_cache_delete(key) > 0

    def close(self) -> None:
        """Close underlying cache handle."""
        close_fn = getattr(self._cache, "close", None)
        if callable(close_fn):
            close_fn()

    # ─── Internals ──────────────────────────────────────────────────────
    @staticmethod
    def _build_prices_cache_key(
        ticker: str, exchange: str, timeframe: str
    ) -> str:
        """Produce a deterministic cache key for prices."""
        # Le chiavi cache sono convenzionate con prefisso di tipo per
        # facilitare listing e invalidation bulk nei test
        return f"prices:{ticker}:{exchange}:{timeframe}"

    @staticmethod
    def _build_macro_cache_key(series_id: str) -> str:
        """Produce a deterministic cache key for macro series."""
        return f"macro:{series_id}"

    def _safe_cache_set(self, key: str, value: Any, ttl: int | None) -> bool:
        """Write to cache ignoring backend failures (cache must never break app)."""
        try:
            # diskcache.Cache.set(key, value, expire=seconds)
            result = self._cache.set(key, value, expire=ttl)
            return bool(result)
        except (OSError, DataError, RuntimeError) as exc:
            log.warning("dual_writer.cache_set_failed", key=key, error=str(exc))
            return False

    def _safe_cache_get(self, key: str) -> Any:
        """Read from cache, defaulting to None on any error."""
        try:
            return self._cache.get(key, default=None)
        except (OSError, DataError, RuntimeError) as exc:
            log.warning("dual_writer.cache_get_failed", key=key, error=str(exc))
            return None

    def _safe_cache_delete(self, key: str) -> int:
        """Delete from cache; returns 1 on hit, 0 otherwise."""
        try:
            return int(self._cache.delete(key))
        except (OSError, DataError, RuntimeError) as exc:
            log.warning("dual_writer.cache_delete_failed", key=key, error=str(exc))
            return 0


# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════
_INSTANCE: DualWriter | None = None


def get_dual_writer() -> DualWriter:
    """Return the process-wide DualWriter singleton."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = DualWriter()
    return _INSTANCE


def reset_dual_writer() -> None:
    """Reset the singleton (tests only)."""
    global _INSTANCE
    if _INSTANCE is not None:
        _INSTANCE.close()
        _INSTANCE = None
