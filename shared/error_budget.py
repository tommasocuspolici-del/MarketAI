"""Error budget manager (Rule 30).

Tracks error rate over a sliding window. If the rate exceeds the configured
threshold, exposes an ``is_tripped`` flag that the scheduler consults
to auto-suspend operations.

SLA targets (from Rule 30):
  · Query analysis P95 latency ≤ 2s
  · Scheduler uptime ≥ 99%
  · If error_rate over 5min > 10% → scheduler auto-suspends + notifies
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass

from shared.constants import (
    DEFAULT_ERROR_BUDGET_THRESHOLD_PCT,
    DEFAULT_ERROR_BUDGET_WINDOW_MINUTES,
)
from shared.logger import get_logger

__version__ = "6.0.0"

__all__ = ["BudgetStatus", "ErrorBudget", "error_budget"]

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class BudgetStatus:
    """Snapshot of the error budget state."""

    window_minutes: int
    threshold_pct: float
    total_events: int
    error_events: int
    error_rate_pct: float
    tripped: bool


@dataclass(slots=True)
class _Event:
    """Single tracked event."""

    ts: float
    is_error: bool


class ErrorBudget:
    """Sliding window error budget tracker.

    Records success / failure events. Computes the rolling error rate over
    a configurable window and exposes ``is_tripped`` once the threshold
    is breached.
    """

    def __init__(
        self,
        window_minutes: int | None = None,
        threshold_pct: float | None = None,
    ) -> None:
        # Preferisci env var (configurabile in produzione), poi i default
        env_window = os.getenv("ERROR_BUDGET_WINDOW_MINUTES")
        env_threshold = os.getenv("ERROR_BUDGET_THRESHOLD_PCT")

        self._window_seconds: float = float(
            (window_minutes or (int(env_window) if env_window else DEFAULT_ERROR_BUDGET_WINDOW_MINUTES))
            * 60
        )
        self._threshold_pct: float = float(
            threshold_pct
            or (float(env_threshold) if env_threshold else DEFAULT_ERROR_BUDGET_THRESHOLD_PCT)
        )

        self._events: deque[_Event] = deque()
        self._lock = threading.Lock()
        self._tripped_since: float | None = None

    # ─── Recording ────────────────────────────────────────────────────────
    def record_success(self) -> None:
        """Record a successful operation."""
        self._record(is_error=False)

    def record_error(self) -> None:
        """Record a failed operation."""
        self._record(is_error=True)

    def _record(self, is_error: bool) -> None:
        now = time.monotonic()
        with self._lock:
            self._events.append(_Event(ts=now, is_error=is_error))
            self._gc_locked(now)
            # Riesame automatico dello stato ad ogni evento
            self._reevaluate_locked(now)

    # ─── Garbage collection ──────────────────────────────────────────────
    def _gc_locked(self, now: float) -> None:
        """Remove events outside the window. Caller holds lock."""
        cutoff = now - self._window_seconds
        while self._events and self._events[0].ts < cutoff:
            self._events.popleft()

    # ─── State evaluation ───────────────────────────────────────────────
    def _reevaluate_locked(self, now: float) -> None:
        """Update `is_tripped` flag. Caller holds lock."""
        if not self._events:
            self._tripped_since = None
            return
        total = len(self._events)
        errors = sum(1 for e in self._events if e.is_error)
        rate_pct = (errors / total) * 100.0

        if rate_pct > self._threshold_pct:
            if self._tripped_since is None:
                self._tripped_since = now
                log.warning(
                    "error_budget.tripped",
                    error_rate_pct=rate_pct,
                    threshold_pct=self._threshold_pct,
                    total=total,
                    errors=errors,
                )
        else:
            if self._tripped_since is not None:
                log.info(
                    "error_budget.recovered",
                    error_rate_pct=rate_pct,
                    threshold_pct=self._threshold_pct,
                )
            self._tripped_since = None

    # ─── Public API ──────────────────────────────────────────────────────
    @property
    def is_tripped(self) -> bool:
        """Whether the error budget is currently exceeded."""
        with self._lock:
            self._gc_locked(time.monotonic())
            self._reevaluate_locked(time.monotonic())
            return self._tripped_since is not None

    def status(self) -> BudgetStatus:
        """Return a snapshot of the current state."""
        with self._lock:
            now = time.monotonic()
            self._gc_locked(now)
            total = len(self._events)
            errors = sum(1 for e in self._events if e.is_error)
            rate = (errors / total * 100.0) if total else 0.0
            return BudgetStatus(
                window_minutes=int(self._window_seconds // 60),
                threshold_pct=self._threshold_pct,
                total_events=total,
                error_events=errors,
                error_rate_pct=rate,
                tripped=self._tripped_since is not None,
            )

    def reset(self) -> None:
        """Reset internal state (for tests)."""
        with self._lock:
            self._events.clear()
            self._tripped_since = None


# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════
error_budget: ErrorBudget = ErrorBudget()
