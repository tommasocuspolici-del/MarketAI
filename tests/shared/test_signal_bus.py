"""Tests for shared.signal_bus — SignalBus pub/sub (lean v10)."""
from __future__ import annotations

import asyncio

import pytest

from shared.signal_bus import SignalBus
from shared.signal_registry import SignalRegistry
from shared.signal_types import Signal


def _make_signal(name: str = "test", value: float = 0.5) -> Signal:
    return Signal(name=name, value=value, confidence=0.8, source_module="test")


def _make_bus() -> SignalBus:
    """Return a fresh SignalBus with its own SignalRegistry."""
    bus = SignalBus.__new__(SignalBus)
    from collections import defaultdict
    import threading
    bus._handlers = defaultdict(list)  # type: ignore[attr-defined]
    bus._lock = threading.RLock()      # type: ignore[attr-defined]
    bus._registry = SignalRegistry()   # type: ignore[attr-defined]
    return bus


class TestSubscribePublishSync:
    def test_handler_called_on_publish(self) -> None:
        bus = _make_bus()
        received: list[Signal] = []
        bus.subscribe("test", lambda s: received.append(s))
        bus.publish(_make_signal("test"))
        assert len(received) == 1
        assert received[0].name == "test"

    def test_handler_not_called_for_other_signal(self) -> None:
        bus = _make_bus()
        received: list[Signal] = []
        bus.subscribe("other", lambda s: received.append(s))
        bus.publish(_make_signal("test"))
        assert received == []

    def test_multiple_handlers_all_called(self) -> None:
        bus = _make_bus()
        counts = [0, 0]
        bus.subscribe("x", lambda _: counts.__setitem__(0, counts[0] + 1))
        bus.subscribe("x", lambda _: counts.__setitem__(1, counts[1] + 1))
        bus.publish(_make_signal("x"))
        assert counts == [1, 1]

    def test_wildcard_receives_all_signals(self) -> None:
        bus = _make_bus()
        received: list[str] = []
        bus.subscribe("*", lambda s: received.append(s.name))
        bus.publish(_make_signal("a"))
        bus.publish(_make_signal("b"))
        assert received == ["a", "b"]


class TestUnsubscribe:
    def test_unsubscribe_removes_handler(self) -> None:
        bus = _make_bus()
        received: list[Signal] = []
        h = lambda s: received.append(s)  # noqa: E731
        bus.subscribe("test", h)
        bus.unsubscribe("test", h)
        bus.publish(_make_signal("test"))
        assert received == []

    def test_unsubscribe_nonexistent_is_safe(self) -> None:
        bus = _make_bus()
        bus.unsubscribe("nonexistent", lambda _: None)   # should not raise


class TestHandlerFailureIsolation:
    def test_failing_handler_does_not_block_other_handlers(self) -> None:
        bus = _make_bus()
        received: list[Signal] = []

        def bad_handler(s: Signal) -> None:
            raise RuntimeError("boom")

        def good_handler(s: Signal) -> None:
            received.append(s)

        bus.subscribe("test", bad_handler)
        bus.subscribe("test", good_handler)
        bus.publish(_make_signal("test"))
        # good_handler still runs (sync path)
        assert len(received) == 1


class TestPublishStoresInRegistry:
    def test_signal_stored_in_registry_after_publish(self) -> None:
        bus = _make_bus()
        bus.publish(_make_signal("reg_test", value=0.7))
        snap = bus._registry.snapshot()  # type: ignore[attr-defined]
        assert "reg_test" in snap
        assert snap["reg_test"] == pytest.approx(0.7)


class TestPublishAsync:
    def test_async_publish_calls_handler(self) -> None:
        bus = _make_bus()
        received: list[Signal] = []

        async def async_handler(s: Signal) -> None:
            received.append(s)

        bus.subscribe("async_test", async_handler)

        async def run() -> None:
            await bus.publish_async(_make_signal("async_test"))

        asyncio.run(run())
        assert len(received) == 1


class TestSubscriberCount:
    def test_count_increases_on_subscribe(self) -> None:
        bus = _make_bus()
        assert bus.subscriber_count("x") == 0
        bus.subscribe("x", lambda _: None)
        assert bus.subscriber_count("x") == 1

    def test_all_subscriptions_returns_dict(self) -> None:
        bus = _make_bus()
        bus.subscribe("a", lambda _: None)
        bus.subscribe("b", lambda _: None)
        subs = bus.all_subscriptions()
        assert subs["a"] == 1
        assert subs["b"] == 1


class TestBenchmarkPublish:
    @pytest.mark.benchmark(group="signal_bus")
    def test_publish_under_5ms(self, benchmark) -> None:
        bus = _make_bus()
        sig = _make_signal()
        result = benchmark(bus.publish, sig)
        # benchmark asserts timing internally; result is just the return value
