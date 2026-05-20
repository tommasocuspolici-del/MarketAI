"""Tests for shared.monitoring.log_store."""
from __future__ import annotations

from shared.monitoring.log_store import (
    InMemoryLogStore,
    clear_logs,
    get_recent_logs,
)


class TestInMemoryLogStore:
    def setup_method(self) -> None:
        clear_logs()

    def test_processor_returns_event_dict(self) -> None:
        proc = InMemoryLogStore()
        event_dict = {"event": "test.event", "key": "value"}
        result = proc(None, "info", event_dict)
        assert result is event_dict  # passthrough

    def test_event_captured(self) -> None:
        proc = InMemoryLogStore()
        proc(None, "info", {"event": "hello.world"})
        logs = get_recent_logs(limit=10)
        assert any(e["event"] == "hello.world" for e in logs)

    def test_level_uppercased(self) -> None:
        proc = InMemoryLogStore()
        proc(None, "warning", {"event": "test.warn"})
        logs = get_recent_logs()
        assert any(e["level"] == "WARNING" for e in logs)

    def test_extra_fields_captured(self) -> None:
        proc = InMemoryLogStore()
        proc(None, "info", {"event": "ctx.test", "ticker": "AAPL", "value": "42"})
        logs = get_recent_logs()
        entry = next(e for e in logs if e["event"] == "ctx.test")
        assert entry["ticker"] == "AAPL"

    def test_long_values_truncated(self) -> None:
        proc = InMemoryLogStore()
        long_val = "x" * 200
        proc(None, "info", {"event": "long.field", "data": long_val})
        logs = get_recent_logs()
        entry = next(e for e in logs if e["event"] == "long.field")
        assert len(entry["data"]) <= 80

    def test_clear_empties_store(self) -> None:
        proc = InMemoryLogStore()
        proc(None, "info", {"event": "before.clear"})
        clear_logs()
        assert get_recent_logs() == []


class TestGetRecentLogs:
    def setup_method(self) -> None:
        clear_logs()

    def test_returns_list(self) -> None:
        assert isinstance(get_recent_logs(), list)

    def test_empty_when_no_logs(self) -> None:
        assert get_recent_logs() == []

    def test_limit_respected(self) -> None:
        proc = InMemoryLogStore()
        for i in range(20):
            proc(None, "info", {"event": f"evt.{i}"})
        result = get_recent_logs(limit=5)
        assert len(result) == 5

    def test_newest_last(self) -> None:
        proc = InMemoryLogStore()
        proc(None, "info", {"event": "first"})
        proc(None, "info", {"event": "last"})
        result = get_recent_logs(limit=10)
        events = [e["event"] for e in result]
        assert events.index("last") > events.index("first")
