"""Runtime metrics collection.

Lightweight, process-local counters & histograms. No external dependency
on Prometheus / OTEL at this stage — the HealthChecker scrapes these
directly. Can be swapped for a real metrics backend later without changing
call sites.

Usage:
    from shared.metrics import metrics

    metrics.inc("fetch_errors_total", source="finnhub")
    with metrics.timer("pipeline_duration_ms", stage="clean"):
        ...
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from shared.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

__version__ = "6.0.0"

__all__ = ["Metrics", "metrics"]

log = get_logger(__name__)

_MAX_HISTOGRAM_SAMPLES: int = 1024


def _label_key(labels: dict[str, str]) -> str:
    """Deterministic key derived from label dict."""
    # Serializzazione deterministica per aggregare counter con stesse label
    if not labels:
        return ""
    return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))


@dataclass(slots=True)
class _Histogram:
    """Fixed-capacity histogram of durations (ms)."""

    samples: deque[float] = field(default_factory=lambda: deque(maxlen=_MAX_HISTOGRAM_SAMPLES))

    def record(self, value_ms: float) -> None:
        self.samples.append(value_ms)

    def snapshot(self) -> dict[str, float]:
        if not self.samples:
            return {"count": 0, "mean_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0}
        sorted_samples = sorted(self.samples)
        n = len(sorted_samples)

        def _pct(p: float) -> float:
            # Percentile con interpolazione lineare semplice
            idx = int(n * p / 100)
            idx = min(idx, n - 1)
            return sorted_samples[idx]

        return {
            "count": float(n),
            "mean_ms": sum(sorted_samples) / n,
            "p50_ms": _pct(50),
            "p95_ms": _pct(95),
            "p99_ms": _pct(99),
        }


class Metrics:
    """Process-local metrics registry. Thread-safe."""

    def __init__(self) -> None:
        self._counters: dict[tuple[str, str], int] = defaultdict(int)
        self._gauges: dict[tuple[str, str], float] = {}
        self._histograms: dict[tuple[str, str], _Histogram] = defaultdict(_Histogram)
        self._lock = threading.Lock()

    # ─── Counters ────────────────────────────────────────────────────────
    def inc(self, name: str, amount: int = 1, **labels: str) -> None:
        """Increment a counter by `amount`."""
        key = (name, _label_key(labels))
        with self._lock:
            self._counters[key] += amount

    def counter(self, name: str, **labels: str) -> int:
        """Read a counter's current value."""
        key = (name, _label_key(labels))
        with self._lock:
            return self._counters[key]

    # ─── Gauges ──────────────────────────────────────────────────────────
    def set_gauge(self, name: str, value: float, **labels: str) -> None:
        """Set a gauge to an absolute value."""
        key = (name, _label_key(labels))
        with self._lock:
            self._gauges[key] = value

    def gauge(self, name: str, **labels: str) -> float:
        """Read a gauge's current value (0 if not set)."""
        key = (name, _label_key(labels))
        with self._lock:
            return self._gauges.get(key, 0.0)

    # ─── Histograms / timers ────────────────────────────────────────────
    def observe(self, name: str, value_ms: float, **labels: str) -> None:
        """Record a histogram observation (in milliseconds)."""
        key = (name, _label_key(labels))
        with self._lock:
            self._histograms[key].record(value_ms)

    @contextmanager
    def timer(self, name: str, **labels: str) -> Iterator[None]:
        """Context manager that records elapsed wall time in milliseconds."""
        t0 = time.monotonic()
        try:
            yield
        finally:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            self.observe(name, elapsed_ms, **labels)

    def histogram_snapshot(self, name: str, **labels: str) -> dict[str, float]:
        """Return percentile snapshot for a histogram."""
        key = (name, _label_key(labels))
        with self._lock:
            hist = self._histograms.get(key)
            if hist is None:
                return {"count": 0, "mean_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0}
            return hist.snapshot()

    # ─── Dump for health / debug ────────────────────────────────────────
    def dump(self) -> dict[str, object]:
        """Return a full snapshot suitable for serialization."""
        with self._lock:
            return {
                "counters": {
                    f"{name}{{{labels}}}" if labels else name: value
                    for (name, labels), value in self._counters.items()
                },
                "gauges": {
                    f"{name}{{{labels}}}" if labels else name: value
                    for (name, labels), value in self._gauges.items()
                },
                "histograms": {
                    f"{name}{{{labels}}}" if labels else name: hist.snapshot()
                    for (name, labels), hist in self._histograms.items()
                },
            }

    def reset(self) -> None:
        """Reset all metrics. Primarily for tests."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


# ═══════════════════════════════════════════════════════════════════════════
# Process-wide singleton
# ═══════════════════════════════════════════════════════════════════════════
metrics: Metrics = Metrics()
