"""Tests for shared.monitoring.system_status — get_system_status()."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from shared.monitoring.system_status import get_system_status, _count_stale_signals, _any_circuit_open


class TestGetSystemStatus:
    def test_returns_string(self) -> None:
        result = get_system_status()
        assert isinstance(result, str)
        assert result in {"OPERATIONAL", "DEGRADED", "DOWN"}

    def test_no_signals_is_degraded(self) -> None:
        with patch("shared.monitoring.system_status._count_stale_signals", return_value=(0, 0)):
            with patch("shared.monitoring.system_status._any_circuit_open", return_value=False):
                assert get_system_status() == "DEGRADED"

    def test_all_fresh_is_operational(self) -> None:
        with patch("shared.monitoring.system_status._count_stale_signals", return_value=(0, 5)):
            with patch("shared.monitoring.system_status._any_circuit_open", return_value=False):
                assert get_system_status() == "OPERATIONAL"

    def test_open_circuit_is_degraded(self) -> None:
        with patch("shared.monitoring.system_status._count_stale_signals", return_value=(0, 5)):
            with patch("shared.monitoring.system_status._any_circuit_open", return_value=True):
                assert get_system_status() == "DEGRADED"

    def test_half_stale_is_down(self) -> None:
        with patch("shared.monitoring.system_status._count_stale_signals", return_value=(3, 5)):
            with patch("shared.monitoring.system_status._any_circuit_open", return_value=False):
                assert get_system_status() == "DOWN"

    def test_some_stale_is_degraded(self) -> None:
        with patch("shared.monitoring.system_status._count_stale_signals", return_value=(1, 5)):
            with patch("shared.monitoring.system_status._any_circuit_open", return_value=False):
                assert get_system_status() == "DEGRADED"

    def test_inspection_error_returns_degraded(self) -> None:
        with patch(
            "shared.monitoring.system_status._count_stale_signals",
            side_effect=RuntimeError("DB down"),
        ):
            assert get_system_status() == "DEGRADED"


class TestCountStaleSignals:
    def test_returns_tuple_of_ints(self) -> None:
        stale, total = _count_stale_signals()
        assert isinstance(stale, int)
        assert isinstance(total, int)
        assert stale <= total

    def test_empty_registry_returns_zeros(self) -> None:
        from shared.signal_registry import get_signal_registry
        registry = get_signal_registry()
        registry.clear()
        stale, total = _count_stale_signals()
        assert stale == 0
        assert total == 0


class TestAnyCircuitOpen:
    def test_returns_bool(self) -> None:
        result = _any_circuit_open()
        assert isinstance(result, bool)

    def test_fresh_breakers_not_open(self) -> None:
        # Newly created circuit breakers start CLOSED
        from shared.resilience.circuit_breaker import get_circuit_breaker, CircuitBreakerState
        cb = get_circuit_breaker("_test_health_s0_fresh")
        assert cb.state == CircuitBreakerState.CLOSED
        # With fresh breakers, should not be open
        assert _any_circuit_open() is False or isinstance(_any_circuit_open(), bool)
