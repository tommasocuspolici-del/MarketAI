"""Rate limit manager (Rule 28).

Single source of truth for all external API rate limiting.
Every fetcher MUST acquire() before calling an external API.

Enforces:
  · requests_per_minute (sliding window over last 60s)
  · requests_per_day    (rolling 24h window)
  · min_interval        (between consecutive calls)
  · burst_size          (informative; soft cap handled by sliding window)

Auto-sleep when rate is saturated. Raises RateLimitExceededError only when
the daily budget is exhausted.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import yaml

from shared.constants import RATE_LIMITS_PATH
from shared.exceptions import ConfigurationError, RateLimitExceededError
from shared.logger import get_logger

if TYPE_CHECKING:
    from pathlib import Path

__version__ = "6.0.0"

__all__ = ["RateBudget", "RateLimitManager", "get_rate_limiter"]

log = get_logger(__name__)

_UNLIMITED: str = "unlimited"
_SECONDS_PER_DAY: int = 86_400
_SECONDS_PER_MINUTE: int = 60


# ═══════════════════════════════════════════════════════════════════════════
# Budget config
# ═══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class RateBudget:
    """Rate limit budget for a single data source."""

    name: str
    requests_per_minute: int
    requests_per_day: int | None  # None == unlimited
    burst_size: int = 3

    @property
    def min_interval_secs(self) -> float:
        """Minimum interval between two consecutive calls (seconds)."""
        if self.requests_per_minute <= 0:
            return 0.0
        return _SECONDS_PER_MINUTE / self.requests_per_minute


@dataclass(slots=True)
class _Tracker:
    """Internal runtime state for a single source."""

    budget: RateBudget
    minute_window: deque[float] = field(default_factory=deque)
    day_count: int = 0
    day_reset_ts: float = field(default_factory=time.monotonic)
    last_request_ts: float = 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Manager
# ═══════════════════════════════════════════════════════════════════════════
class RateLimitManager:
    """Centralized rate limiter. Single instance per process."""

    def __init__(self, config_path: Path = RATE_LIMITS_PATH) -> None:
        self._trackers: dict[str, _Tracker] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._load_config(config_path)

    # ─── Configuration ────────────────────────────────────────────────────
    def _load_config(self, path: Path) -> None:
        if not path.exists():
            log.warning("rate_limiter.config_missing", path=str(path))
            return

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ConfigurationError(
                f"Rate limits file {path} must be a mapping, got {type(raw).__name__}"
            )

        for source, cfg in raw.items():
            if not isinstance(cfg, dict):
                log.warning("rate_limiter.invalid_source_config", source=source)
                continue

            # Normalizzazione campo requests_per_day: accetta int o "unlimited"
            raw_day = cfg.get("requests_per_day", _UNLIMITED)
            day_limit: int | None
            if isinstance(raw_day, int):
                day_limit = raw_day
            elif isinstance(raw_day, str) and raw_day.lower() == _UNLIMITED:
                day_limit = None
            else:
                log.warning(
                    "rate_limiter.invalid_daily_limit",
                    source=source,
                    value=raw_day,
                )
                day_limit = None

            budget = RateBudget(
                name=source,
                requests_per_minute=int(cfg.get("requests_per_minute", 60)),
                requests_per_day=day_limit,
                burst_size=int(cfg.get("burst_size", 3)),
            )
            self._trackers[source] = _Tracker(budget=budget)
            self._locks[source] = asyncio.Lock()

        log.info("rate_limiter.loaded", sources=sorted(self._trackers.keys()))

    # ─── Public API ──────────────────────────────────────────────────────
    async def acquire(self, source: str) -> None:
        """Acquire permission to make one request. Sleeps if throttled.

        Args:
            source: Key matching config/rate_limits.yaml (e.g. "finnhub").

        Raises:
            RateLimitExceededError: If daily budget is exhausted.
        """
        if source not in self._trackers:
            # Sorgenti non configurate passano (permissivo), ma vengono tracciate
            log.warning("rate_limiter.unknown_source", source=source)
            return

        # Blocco asyncio: garantisce serializzazione delle decisioni di throttling
        async with self._locks[source]:
            await self._acquire_locked(source)

    async def _acquire_locked(self, source: str) -> None:
        tracker = self._trackers[source]
        budget = tracker.budget
        now = time.monotonic()

        # Reset contatore giornaliero se è trascorso un giorno
        if now - tracker.day_reset_ts > _SECONDS_PER_DAY:
            tracker.day_count = 0
            tracker.day_reset_ts = now

        # Verifica budget giornaliero
        if budget.requests_per_day is not None and tracker.day_count >= budget.requests_per_day:
            raise RateLimitExceededError(source=source, limit_type="daily")

        # Pulizia sliding window: rimuovi timestamp > 60s fa
        cutoff = now - _SECONDS_PER_MINUTE
        while tracker.minute_window and tracker.minute_window[0] < cutoff:
            tracker.minute_window.popleft()

        # Se la finestra di 60s è piena, attendi il rilascio del più vecchio
        if len(tracker.minute_window) >= budget.requests_per_minute:
            oldest = tracker.minute_window[0]
            wait_secs = _SECONDS_PER_MINUTE - (now - oldest) + 0.05
            if wait_secs > 0:
                log.debug("rate_limiter.throttling", source=source, wait=wait_secs)
                await asyncio.sleep(wait_secs)
                now = time.monotonic()
                # Dopo il sleep, ripulisci ancora la finestra
                cutoff = now - _SECONDS_PER_MINUTE
                while tracker.minute_window and tracker.minute_window[0] < cutoff:
                    tracker.minute_window.popleft()

        # Garanzia intervallo minimo fra richieste consecutive
        elapsed = now - tracker.last_request_ts
        if tracker.last_request_ts > 0 and elapsed < budget.min_interval_secs:
            wait_secs = budget.min_interval_secs - elapsed
            await asyncio.sleep(wait_secs)
            now = time.monotonic()

        # Registra la richiesta
        tracker.minute_window.append(now)
        tracker.last_request_ts = now
        tracker.day_count += 1

        log.debug(
            "rate_limiter.acquired",
            source=source,
            rpm=len(tracker.minute_window),
            daily=tracker.day_count,
        )

    # ─── Introspection ───────────────────────────────────────────────────
    def get_status(self, source: str) -> dict[str, object]:
        """Return current utilization for a source (for metrics / health)."""
        if source not in self._trackers:
            return {"source": source, "configured": False}
        tracker = self._trackers[source]
        return {
            "source": source,
            "configured": True,
            "rpm_used": len(tracker.minute_window),
            "rpm_limit": tracker.budget.requests_per_minute,
            "daily_used": tracker.day_count,
            "daily_limit": tracker.budget.requests_per_day,
        }

    def list_sources(self) -> list[str]:
        """Return the list of configured sources."""
        return sorted(self._trackers.keys())


# ═══════════════════════════════════════════════════════════════════════════
# Singleton accessor
# ═══════════════════════════════════════════════════════════════════════════
_INSTANCE: RateLimitManager | None = None


def get_rate_limiter() -> RateLimitManager:
    """Return the process-wide RateLimitManager singleton."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = RateLimitManager()
    return _INSTANCE
