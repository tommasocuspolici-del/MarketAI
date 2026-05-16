"""SignalRegistry — in-process store for the latest signal values.

Every module publishes its Signal to SignalBus; the bus forwards a copy
here so consumers can read the current value without hitting DuckDB.

TTL: signals older than their declared TTL are considered stale and are
excluded from snapshot() — preventing stale data from entering the Composite.

Thread-safe via a single RLock.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from shared.logger import get_logger
from shared.signal_types import Signal

__version__ = "10.0.0"

__all__ = [
    "SignalEntry",
    "SignalRegistry",
    "get_signal_registry",
]

log = get_logger(__name__)

_DEFAULT_TTL_SECONDS = 3600        # 1 hour — overridable per-signal


@dataclass
class SignalEntry:
    signal:      Signal
    ttl_seconds: int = _DEFAULT_TTL_SECONDS
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_stale(self) -> bool:
        age = (datetime.now(UTC) - self.received_at).total_seconds()
        return age > self.ttl_seconds


class SignalRegistry:
    """In-process registry of the latest signal per name.

    Usage::

        registry = get_signal_registry()
        registry.publish(signal, ttl_seconds=900)
        snapshot = registry.snapshot()   # dict[name → value], stale excluded
    """

    _DEFAULT_TTLS: ClassVar[dict[str, int]] = {
        "technical_composite":       900,    # 15 min
        "macro_conviction":         3600,    # 1 h
        "labour_regime_signal":    86400,    # 1 day
        "sentiment_composite":      1800,    # 30 min
        "valuation_signal":        86400,    # 1 day
        "economic_surprise_index":  3600,    # 1 h
        "vix_signal":                900,    # 15 min
    }

    def __init__(self) -> None:
        self._store: dict[str, SignalEntry] = {}
        self._lock = threading.RLock()

    def publish(self, signal: Signal, ttl_seconds: int | None = None) -> None:
        """Store the latest value for *signal.name*.

        ttl_seconds: explicit override; falls back to _DEFAULT_TTLS, then
                     _DEFAULT_TTL_SECONDS.
        """
        if ttl_seconds is None:
            ttl_seconds = self._DEFAULT_TTLS.get(signal.name, _DEFAULT_TTL_SECONDS)

        entry = SignalEntry(signal=signal, ttl_seconds=ttl_seconds)
        with self._lock:
            self._store[signal.name] = entry

        log.debug(
            "signal_registry.published",
            name=signal.name,
            value=round(signal.value, 4),
            ttl=ttl_seconds,
        )

    def get(self, signal_name: str) -> Signal | None:
        """Return the latest (possibly stale) Signal for *signal_name*."""
        with self._lock:
            entry = self._store.get(signal_name)
        return entry.signal if entry else None

    def get_fresh(self, signal_name: str) -> Signal | None:
        """Return Signal only if not stale; None otherwise."""
        with self._lock:
            entry = self._store.get(signal_name)
        if entry is None or entry.is_stale:
            return None
        return entry.signal

    def snapshot(self) -> dict[str, float]:
        """Return {signal_name: value} for all non-stale signals."""
        with self._lock:
            entries = list(self._store.items())
        result = {
            name: entry.signal.value
            for name, entry in entries
            if not entry.is_stale
        }
        log.debug("signal_registry.snapshot", n=len(result))
        return result

    def stale_signals(self) -> list[str]:
        """Return names of signals whose TTL has expired."""
        with self._lock:
            entries = list(self._store.items())
        return [name for name, entry in entries if entry.is_stale]

    def all_signals(self) -> list[str]:
        with self._lock:
            return list(self._store.keys())

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# ── Module-level singleton ─────────────────────────────────────────────────

_registry: SignalRegistry | None = None
_registry_lock = threading.Lock()


def get_signal_registry() -> SignalRegistry:
    """Return the process-wide SignalRegistry singleton."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = SignalRegistry()
    return _registry
