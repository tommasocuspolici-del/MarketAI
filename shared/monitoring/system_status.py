"""system_status — Aggregate system health for the status pill and S0 page.

Inspects:
  1. SignalRegistry — are any signals stale?
  2. CircuitBreakers — are any OPEN?

Returns a ``SystemStatus`` string: "OPERATIONAL" | "DEGRADED" | "DOWN".

Usage::

    from shared.monitoring.system_status import get_system_status
    status = get_system_status()   # "OPERATIONAL" | "DEGRADED" | "DOWN"
"""
from __future__ import annotations

from typing import Literal

from shared.logger import get_logger

__all__ = ["SystemStatus", "get_system_status"]

log = get_logger(__name__)

SystemStatus = Literal["OPERATIONAL", "DEGRADED", "DOWN"]


def get_system_status() -> SystemStatus:
    """Return the aggregate system health status.

    Checks:
      - SignalRegistry: fraction of stale signals
      - CircuitBreakers: any OPEN breakers

    Priority: DOWN > DEGRADED > OPERATIONAL.
    Returns "DEGRADED" on any inspection error (conservative default).
    """
    try:
        stale_count, total = _count_stale_signals()
        cb_open = _any_circuit_open()
    except Exception as exc:
        log.warning("system_status.inspection_failed", error=str(exc))
        return "DEGRADED"

    if cb_open:
        return "DEGRADED"

    if total == 0:
        # No signals yet — system starting up
        return "DEGRADED"

    stale_fraction = stale_count / total
    if stale_fraction >= 0.5:
        return "DOWN"
    if stale_fraction > 0:
        return "DEGRADED"

    return "OPERATIONAL"


def _count_stale_signals() -> tuple[int, int]:
    """Return (stale_count, total) from SignalRegistry."""
    from shared.signal_registry import get_signal_registry

    registry = get_signal_registry()
    all_signals = registry.all_signals()
    if not all_signals:
        return 0, 0

    stale = registry.stale_signals()
    return len(stale), len(all_signals)


def _any_circuit_open() -> bool:
    """Return True if any circuit breaker is currently OPEN."""
    try:
        from shared.resilience.circuit_breaker import get_circuit_breaker, CircuitBreakerState

        known_breakers = ["yfinance", "fred", "finnhub", "alpha_vantage"]
        for name in known_breakers:
            cb = get_circuit_breaker(name)
            if cb.state == CircuitBreakerState.OPEN:
                return True
        return False
    except Exception:
        return False
