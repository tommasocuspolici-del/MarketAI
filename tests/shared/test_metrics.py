"""Tests for shared.metrics."""
from __future__ import annotations

import time

from shared.metrics import Metrics


class TestMetrics:
    def test_counter_increment(self) -> None:
        m = Metrics()
        m.inc("requests")
        m.inc("requests", amount=2)
        assert m.counter("requests") == 3

    def test_counter_with_labels_are_separate(self) -> None:
        m = Metrics()
        m.inc("fetch", source="finnhub")
        m.inc("fetch", source="fred")
        m.inc("fetch", source="finnhub")
        assert m.counter("fetch", source="finnhub") == 2
        assert m.counter("fetch", source="fred") == 1

    def test_gauge_set_and_read(self) -> None:
        m = Metrics()
        m.set_gauge("cpu_pct", 42.5)
        assert m.gauge("cpu_pct") == 42.5

    def test_gauge_default_zero(self) -> None:
        m = Metrics()
        assert m.gauge("never_set") == 0.0

    def test_timer_records_observation(self) -> None:
        m = Metrics()
        with m.timer("op_ms"):
            time.sleep(0.01)
        snap = m.histogram_snapshot("op_ms")
        assert snap["count"] == 1
        assert snap["mean_ms"] >= 10.0

    def test_histogram_percentiles(self) -> None:
        m = Metrics()
        for v in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]:
            m.observe("lat", float(v))
        snap = m.histogram_snapshot("lat")
        assert snap["count"] == 10
        assert snap["p50_ms"] >= 5
        assert snap["p95_ms"] >= 9

    def test_dump_returns_all_metrics(self) -> None:
        m = Metrics()
        m.inc("a")
        m.set_gauge("b", 1.0)
        m.observe("c", 5.0)
        dump = m.dump()
        assert "counters" in dump
        assert "gauges" in dump
        assert "histograms" in dump

    def test_reset_clears_everything(self) -> None:
        m = Metrics()
        m.inc("x")
        m.set_gauge("y", 1.0)
        m.observe("z", 1.0)
        m.reset()
        assert m.counter("x") == 0
        assert m.gauge("y") == 0.0
        assert m.histogram_snapshot("z")["count"] == 0
