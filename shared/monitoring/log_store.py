"""log_store — In-memory circular buffer of recent structured log events.

Collects log records from structlog processors so Tab 7 of S0 can display
the last N events without reading from disk.

Usage::

    # In structlog configuration (configure_logging):
    from shared.monitoring.log_store import InMemoryLogStore
    InMemoryLogStore.install()   # adds the processor to structlog chain

    # In S0 tab 7:
    from shared.monitoring.log_store import get_recent_logs
    entries = get_recent_logs(limit=50)   # list[dict]
"""
from __future__ import annotations

import threading
from collections import deque
from datetime import UTC, datetime
from typing import Any

__all__ = ["InMemoryLogStore", "get_recent_logs"]

_MAX_ENTRIES = 200
_store: deque[dict[str, Any]] = deque(maxlen=_MAX_ENTRIES)
_lock = threading.Lock()


class InMemoryLogStore:
    """structlog processor that captures log events into an in-memory buffer."""

    @staticmethod
    def install() -> None:
        """No-op: registration happens via structlog config.

        Call this during configure_logging() to signal intent;
        actual integration requires adding ``InMemoryLogStore()`` to the
        processor chain in shared/logger.py.
        """

    def __call__(self, logger: Any, method: str, event_dict: dict) -> dict:
        """structlog processor: copy event to in-memory buffer."""
        record = {
            "timestamp": datetime.now(UTC).strftime("%H:%M:%S"),
            "level":     method.upper(),
            "event":     event_dict.get("event", ""),
            "logger":    event_dict.get("_record", {}).get("name", "") if hasattr(event_dict.get("_record"), "name") else "",
        }
        # Copy any extra context fields (exclude internal structlog keys)
        for k, v in event_dict.items():
            if k not in {"event", "timestamp", "_record", "level", "exc_info"}:
                record[k] = str(v)[:80]   # truncate long values

        with _lock:
            _store.append(record)
        return event_dict


def get_recent_logs(limit: int = 50) -> list[dict[str, Any]]:
    """Return the most recent log events (newest last).

    Args:
        limit: Maximum number of entries to return.

    Returns:
        List of dicts with keys: timestamp, level, event, + any context fields.
    """
    with _lock:
        entries = list(_store)
    return entries[-limit:]


def clear_logs() -> None:
    """Clear the in-memory log buffer (used in tests)."""
    with _lock:
        _store.clear()
