"""CircuitBreaker — protezione contro cascate di failure (Fase 3 Hardening).

Pattern: CLOSED → OPEN → HALF_OPEN → CLOSED

  CLOSED    — operazioni passano; se failure_threshold errori in failure_window_s
              → transizione a OPEN.
  OPEN      — operazioni bloccate (raise CircuitOpenError); dopo recovery_timeout_s
              → transizione a HALF_OPEN.
  HALF_OPEN — una singola operazione di test; se passa → CLOSED, altrimenti → OPEN.

Thread-safe via threading.Lock.
Tutte le soglie da config (no magic numbers — Regola 7).

Usage::

    cb = CircuitBreaker("yfinance", failure_threshold=5, recovery_timeout_s=60)

    try:
        with cb:
            result = yfinance.download(...)
    except CircuitOpenError:
        return cached_fallback()
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from shared.exceptions import DataError
from shared.logger import get_logger

__version__ = "1.0.0"
__all__ = [
    "CircuitBreaker", "CircuitBreakerState", "CircuitOpenError",
    "CircuitBreakerStats", "get_circuit_breaker",
]

log = get_logger(__name__)


class CircuitBreakerState(str, Enum):
    CLOSED     = "closed"      # normal operation
    OPEN       = "open"        # blocking calls
    HALF_OPEN  = "half_open"   # testing recovery


class CircuitOpenError(DataError):
    """Raised when a circuit breaker is OPEN and blocks the call."""


@dataclass(frozen=True)
class CircuitBreakerStats:
    """Snapshot of circuit breaker metrics."""
    name:              str
    state:             CircuitBreakerState
    failure_count:     int
    success_count:     int
    last_failure_at:   float | None     # monotonic timestamp
    last_success_at:   float | None
    total_calls:       int
    total_rejected:    int


class CircuitBreaker:
    """Thread-safe circuit breaker for external API calls.

    Args:
        name:              Identifier (used in logs and metrics).
        failure_threshold: Consecutive/windowed failures before OPEN (default: 5).
        failure_window_s:  Window for counting failures in seconds (default: 60).
        recovery_timeout_s: Time before OPEN → HALF_OPEN (default: 30).
        success_threshold: Successes in HALF_OPEN before CLOSED (default: 1).
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int   = 5,
        failure_window_s:  float = 60.0,
        recovery_timeout_s: float = 30.0,
        success_threshold: int   = 1,
    ) -> None:
        self._name              = name
        self._failure_threshold = failure_threshold
        self._failure_window_s  = failure_window_s
        self._recovery_timeout  = recovery_timeout_s
        self._success_threshold = success_threshold

        self._lock              = threading.Lock()
        self._state             = CircuitBreakerState.CLOSED
        self._failure_times: deque[float] = deque()   # monotonic timestamps
        self._half_open_successes = 0
        self._last_failure_at:  float | None = None
        self._last_success_at:  float | None = None
        self._total_calls       = 0
        self._total_rejected    = 0

    # ── Context-manager interface ───────────────────────────────────────────

    def __enter__(self) -> "CircuitBreaker":
        self._before_call()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        if exc_type is None:
            self._on_success()
        else:
            self._on_failure()
        return False  # do not suppress exceptions

    # ── Call wrappers ───────────────────────────────────────────────────────

    def call(self, fn, *args: Any, **kwargs: Any) -> Any:
        """Execute fn(*args, **kwargs) under circuit-breaker protection."""
        with self:
            return fn(*args, **kwargs)

    # ── State inspection ────────────────────────────────────────────────────

    @property
    def state(self) -> CircuitBreakerState:
        with self._lock:
            self._maybe_transition()
            return self._state

    @property
    def is_open(self) -> bool:
        return self.state == CircuitBreakerState.OPEN

    @property
    def is_closed(self) -> bool:
        return self.state == CircuitBreakerState.CLOSED

    def stats(self) -> CircuitBreakerStats:
        with self._lock:
            self._maybe_transition()
            return CircuitBreakerStats(
                name=self._name,
                state=self._state,
                failure_count=len(self._failure_times),
                success_count=self._half_open_successes,
                last_failure_at=self._last_failure_at,
                last_success_at=self._last_success_at,
                total_calls=self._total_calls,
                total_rejected=self._total_rejected,
            )

    def reset(self) -> None:
        """Force circuit back to CLOSED (for testing/admin)."""
        with self._lock:
            self._state = CircuitBreakerState.CLOSED
            self._failure_times.clear()
            self._half_open_successes = 0
            log.info("circuit_breaker.reset", name=self._name)

    # ── Private ─────────────────────────────────────────────────────────────

    def _before_call(self) -> None:
        with self._lock:
            self._maybe_transition()
            self._total_calls += 1
            if self._state == CircuitBreakerState.OPEN:
                self._total_rejected += 1
                raise CircuitOpenError(
                    f"Circuit '{self._name}' is OPEN — calls blocked. "
                    f"Retry after {self._recovery_timeout:.0f}s."
                )

    def _on_success(self) -> None:
        with self._lock:
            self._last_success_at = time.monotonic()
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= self._success_threshold:
                    self._transition_closed()
            # In CLOSED state, clear old failures
            self._prune_old_failures()

    def _on_failure(self) -> None:
        with self._lock:
            now = time.monotonic()
            self._last_failure_at = now
            self._failure_times.append(now)
            self._prune_old_failures()

            if self._state == CircuitBreakerState.HALF_OPEN:
                self._transition_open()
            elif self._state == CircuitBreakerState.CLOSED:
                if len(self._failure_times) >= self._failure_threshold:
                    self._transition_open()

    def _maybe_transition(self) -> None:
        """Check if OPEN circuit should move to HALF_OPEN."""
        if (
            self._state == CircuitBreakerState.OPEN
            and self._last_failure_at is not None
            and (time.monotonic() - self._last_failure_at) >= self._recovery_timeout
        ):
            self._state = CircuitBreakerState.HALF_OPEN
            self._half_open_successes = 0
            log.info("circuit_breaker.half_open", name=self._name)

    def _transition_open(self) -> None:
        self._state = CircuitBreakerState.OPEN
        self._half_open_successes = 0
        log.warning(
            "circuit_breaker.open",
            name=self._name,
            failures=len(self._failure_times),
        )

    def _transition_closed(self) -> None:
        self._state = CircuitBreakerState.CLOSED
        self._failure_times.clear()
        self._half_open_successes = 0
        log.info("circuit_breaker.closed", name=self._name)

    def _prune_old_failures(self) -> None:
        """Remove failure timestamps older than failure_window_s."""
        cutoff = time.monotonic() - self._failure_window_s
        while self._failure_times and self._failure_times[0] < cutoff:
            self._failure_times.popleft()


# ── Global registry ─────────────────────────────────────────────────────────
_registry: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_circuit_breaker(
    name: str,
    failure_threshold: int   = 5,
    failure_window_s:  float = 60.0,
    recovery_timeout_s: float = 30.0,
) -> CircuitBreaker:
    """Return (or create) a named circuit breaker from the global registry."""
    with _registry_lock:
        if name not in _registry:
            _registry[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                failure_window_s=failure_window_s,
                recovery_timeout_s=recovery_timeout_s,
            )
        return _registry[name]
