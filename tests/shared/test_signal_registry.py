"""Tests for shared.signal_registry — SignalRegistry + get_signal_registry."""
from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from shared.signal_registry import SignalEntry, SignalRegistry
from shared.signal_types import Signal


def _make_signal(name: str = "test_signal", value: float = 0.5) -> Signal:
    return Signal(name=name, value=value, confidence=0.8, source_module="test")


class TestSignalRegistryPublishGet:
    def test_publish_then_get(self) -> None:
        reg = SignalRegistry()
        sig = _make_signal()
        reg.publish(sig)
        result = reg.get(sig.name)
        assert result is not None
        assert result.value == pytest.approx(0.5)

    def test_get_unknown_returns_none(self) -> None:
        reg = SignalRegistry()
        assert reg.get("nonexistent") is None

    def test_get_fresh_returns_signal(self) -> None:
        reg = SignalRegistry()
        sig = _make_signal()
        reg.publish(sig, ttl_seconds=60)
        assert reg.get_fresh(sig.name) is not None

    def test_get_fresh_stale_returns_none(self) -> None:
        reg = SignalRegistry()
        sig = _make_signal()
        reg.publish(sig, ttl_seconds=0)
        time.sleep(0.01)
        assert reg.get_fresh(sig.name) is None

    def test_publish_overwrites_previous(self) -> None:
        reg = SignalRegistry()
        reg.publish(_make_signal(value=0.3))
        reg.publish(_make_signal(value=0.9))
        assert reg.get("test_signal").value == pytest.approx(0.9)  # type: ignore[union-attr]


class TestSignalRegistrySnapshot:
    def test_snapshot_includes_fresh(self) -> None:
        reg = SignalRegistry()
        reg.publish(_make_signal("a", 0.3), ttl_seconds=60)
        reg.publish(_make_signal("b", 0.7), ttl_seconds=60)
        snap = reg.snapshot()
        assert snap["a"] == pytest.approx(0.3)
        assert snap["b"] == pytest.approx(0.7)

    def test_snapshot_excludes_stale(self) -> None:
        reg = SignalRegistry()
        reg.publish(_make_signal("fresh"), ttl_seconds=60)
        reg.publish(_make_signal("stale"), ttl_seconds=0)
        time.sleep(0.01)
        snap = reg.snapshot()
        assert "fresh" in snap
        assert "stale" not in snap

    def test_snapshot_empty_registry(self) -> None:
        reg = SignalRegistry()
        assert reg.snapshot() == {}


class TestSignalRegistryStaleDetection:
    def test_stale_signals_returns_expired(self) -> None:
        reg = SignalRegistry()
        reg.publish(_make_signal("x"), ttl_seconds=0)
        time.sleep(0.01)
        assert "x" in reg.stale_signals()

    def test_stale_signals_excludes_fresh(self) -> None:
        reg = SignalRegistry()
        reg.publish(_make_signal("x"), ttl_seconds=3600)
        assert "x" not in reg.stale_signals()


class TestSignalRegistryClear:
    def test_clear_empties_store(self) -> None:
        reg = SignalRegistry()
        reg.publish(_make_signal())
        reg.clear()
        assert reg.snapshot() == {}
        assert reg.all_signals() == []


class TestSignalRegistryAllSignals:
    def test_all_signals_lists_names(self) -> None:
        reg = SignalRegistry()
        reg.publish(_make_signal("a"))
        reg.publish(_make_signal("b"))
        assert set(reg.all_signals()) == {"a", "b"}


class TestSignalEntryStale:
    def test_fresh_entry_not_stale(self) -> None:
        sig = _make_signal()
        entry = SignalEntry(signal=sig, ttl_seconds=60)
        assert not entry.is_stale

    def test_zero_ttl_immediately_stale(self) -> None:
        sig = _make_signal()
        entry = SignalEntry(signal=sig, ttl_seconds=0)
        time.sleep(0.01)
        assert entry.is_stale


class TestDefaultTTLs:
    def test_known_signal_gets_default_ttl(self) -> None:
        reg = SignalRegistry()
        sig = _make_signal("technical_composite")
        reg.publish(sig)
        # TTL for technical_composite = 900 — just verify entry exists and is fresh
        assert reg.get_fresh("technical_composite") is not None
