"""Health check system (Rule 30).

Exposes the global system status as one of:
  · OPERATIONAL — all components nominal
  · DEGRADED    — some components impaired but critical analysis still works
  · DOWN        — impossible to operate (DB unreachable, scheduler crashed, ...)

Used by:
  · /health endpoint in Streamlit (Docker healthcheck target)
  · health_status_bar component (sidebar indicator)
  · error_budget auto-suspend logic
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from shared.error_budget import error_budget
from shared.logger import get_logger
from shared.types import HealthState, now_utc

if TYPE_CHECKING:
    from datetime import datetime

__version__ = "6.0.0"

__all__ = [
    "ComponentHealth",
    "HealthChecker",
    "HealthProbe",
    "SystemHealth",
    "cache_probe_factory",
    "duckdb_probe_factory",
    "scheduler_probe_factory",
    "sqlite_probe_factory",
]

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class ComponentHealth:
    """Health status of a single component."""

    name: str
    status: HealthState
    latency_ms: float | None = None
    message: str | None = None
    checked_at: datetime = field(default_factory=now_utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "latency_ms": self.latency_ms,
            "message": self.message,
            "checked_at": self.checked_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class SystemHealth:
    """Aggregated system health across all components."""

    status: HealthState
    components: list[ComponentHealth]
    checked_at: datetime = field(default_factory=now_utc)

    @property
    def is_operational(self) -> bool:
        return self.status == HealthState.OPERATIONAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "checked_at": self.checked_at.isoformat(),
            "components": [c.to_dict() for c in self.components],
        }


# ═══════════════════════════════════════════════════════════════════════════
# Probe abstraction
# ═══════════════════════════════════════════════════════════════════════════
HealthProbe = Callable[[], ComponentHealth]


def _timed_probe(name: str, probe_fn: Callable[[], None]) -> ComponentHealth:
    """Execute a synchronous probe, measure latency, build ComponentHealth."""
    t0 = time.monotonic()
    try:
        probe_fn()
    except Exception as exc:
        # Una probe fallita produce stato DOWN — il probe stesso deve sollevare
        # eccezioni custom se vuole differenziare DEGRADED vs DOWN
        return ComponentHealth(
            name=name,
            status=HealthState.DOWN,
            latency_ms=(time.monotonic() - t0) * 1000.0,
            message=str(exc),
        )
    latency_ms = (time.monotonic() - t0) * 1000.0
    return ComponentHealth(name=name, status=HealthState.OPERATIONAL, latency_ms=latency_ms)


# ═══════════════════════════════════════════════════════════════════════════
# HealthChecker
# ═══════════════════════════════════════════════════════════════════════════
class HealthChecker:
    """Runs all registered probes and aggregates the global status.

    Components are registered by name. A default set is provided for DuckDB,
    SQLite, cache, scheduler, and error budget; additional probes can be
    added via ``register_probe``.
    """

    def __init__(self) -> None:
        self._probes: dict[str, HealthProbe] = {}

    def register_probe(self, name: str, probe: HealthProbe) -> None:
        """Add or replace a named probe."""
        self._probes[name] = probe
        log.info("health.probe_registered", name=name)

    def check_all(self) -> SystemHealth:
        """Run every registered probe and return the aggregated status."""
        components: list[ComponentHealth] = []
        for name, probe in self._probes.items():
            try:
                components.append(probe())
            except Exception as exc:
                # Protezione: una probe che solleva diventa componente DOWN
                components.append(
                    ComponentHealth(
                        name=name,
                        status=HealthState.DOWN,
                        message=f"probe raised: {exc}",
                    )
                )

        # Probe error-budget sempre aggiunto (introspezione del budget runtime)
        components.append(self._probe_error_budget())

        global_status = self._aggregate(components)
        result = SystemHealth(status=global_status, components=components)
        log.info(
            "health.checked",
            status=global_status.value,
            n_components=len(components),
        )
        return result

    # ─── Built-in probes ─────────────────────────────────────────────────
    @staticmethod
    def _probe_error_budget() -> ComponentHealth:
        status = error_budget.status()
        if status.tripped:
            return ComponentHealth(
                name="error_budget",
                status=HealthState.DEGRADED,
                message=(
                    f"error_rate={status.error_rate_pct:.1f}% > "
                    f"threshold={status.threshold_pct:.1f}%"
                ),
            )
        return ComponentHealth(
            name="error_budget",
            status=HealthState.OPERATIONAL,
            message=f"error_rate={status.error_rate_pct:.1f}%",
        )

    # ─── Aggregation ─────────────────────────────────────────────────────
    @staticmethod
    def _aggregate(components: list[ComponentHealth]) -> HealthState:
        """Aggregate strategy: worst wins. DOWN > DEGRADED > OPERATIONAL."""
        if any(c.status == HealthState.DOWN for c in components):
            return HealthState.DOWN
        if any(c.status == HealthState.DEGRADED for c in components):
            return HealthState.DEGRADED
        return HealthState.OPERATIONAL


# ═══════════════════════════════════════════════════════════════════════════
# Built-in factory probes (used from higher layers to register quick probes)
# ═══════════════════════════════════════════════════════════════════════════
def duckdb_probe_factory(query_fn: Callable[[str], Any]) -> HealthProbe:
    """Build a probe that executes a trivial query via ``query_fn``."""

    def _probe() -> ComponentHealth:
        return _timed_probe("duckdb", lambda: query_fn("SELECT 1"))

    return _probe


def sqlite_probe_factory(exec_fn: Callable[[str], Any]) -> HealthProbe:
    """Build a probe that executes a trivial query on SQLite."""

    def _probe() -> ComponentHealth:
        return _timed_probe("sqlite", lambda: exec_fn("SELECT 1"))

    return _probe


def cache_probe_factory(
    set_fn: Callable[[str, str, int], None],
    get_fn: Callable[[str], Any],
) -> HealthProbe:
    """Build a probe that round-trips a value through the cache."""

    def _probe() -> ComponentHealth:
        def _round_trip() -> None:
            set_fn("__health__", "ok", 10)
            value = get_fn("__health__")
            if value != "ok":
                raise RuntimeError("cache read/write mismatch")

        result = _timed_probe("cache", _round_trip)
        return result

    return _probe


def scheduler_probe_factory(is_running_fn: Callable[[], bool]) -> HealthProbe:
    """Build a probe that checks scheduler liveness.

    Args:
        is_running_fn: Callable returning True if the APScheduler is alive.
            In production this would be ``lambda: scheduler.running``.
    """

    def _probe() -> ComponentHealth:
        try:
            running = bool(is_running_fn())
            if running:
                return ComponentHealth(name="scheduler", status=HealthState.OPERATIONAL)
            return ComponentHealth(
                name="scheduler",
                status=HealthState.DEGRADED,
                message="scheduler is not running",
            )
        except Exception as exc:
            return ComponentHealth(
                name="scheduler",
                status=HealthState.DOWN,
                message=str(exc),
            )

    return _probe
