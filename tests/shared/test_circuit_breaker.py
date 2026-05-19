"""Tests — shared.resilience.circuit_breaker (Fase 3 Hardening v3.0)."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from shared.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerState,
    CircuitOpenError,
    get_circuit_breaker,
)


def _fast_cb(**kw) -> CircuitBreaker:
    """CircuitBreaker con soglie molto basse per test veloci."""
    return CircuitBreaker(
        name="test",
        failure_threshold=kw.get("failure_threshold", 3),
        failure_window_s=kw.get("failure_window_s", 60.0),
        recovery_timeout_s=kw.get("recovery_timeout_s", 0.01),
        success_threshold=kw.get("success_threshold", 1),
    )


class TestCircuitBreakerInitialState:
    def test_starts_closed(self) -> None:
        cb = _fast_cb()
        assert cb.state == CircuitBreakerState.CLOSED

    def test_is_closed_true(self) -> None:
        cb = _fast_cb()
        assert cb.is_closed is True
        assert cb.is_open is False

    def test_stats_initial(self) -> None:
        cb = _fast_cb()
        s = cb.stats()
        assert s.failure_count == 0
        assert s.total_calls == 0
        assert s.total_rejected == 0


class TestCircuitBreakerClosed:
    def test_success_stays_closed(self) -> None:
        cb = _fast_cb()
        with cb:
            pass
        assert cb.state == CircuitBreakerState.CLOSED

    def test_calls_counted(self) -> None:
        cb = _fast_cb()
        for _ in range(3):
            with cb:
                pass
        assert cb.stats().total_calls == 3

    def test_few_failures_stay_closed(self) -> None:
        cb = _fast_cb(failure_threshold=3)
        for _ in range(2):
            try:
                with cb:
                    raise ValueError("fail")
            except ValueError:
                pass
        assert cb.state == CircuitBreakerState.CLOSED

    def test_exceptions_propagate(self) -> None:
        cb = _fast_cb()
        with pytest.raises(ValueError, match="boom"):
            with cb:
                raise ValueError("boom")

    def test_call_method_returns_result(self) -> None:
        cb = _fast_cb()
        result = cb.call(lambda: 42)
        assert result == 42


class TestCircuitBreakerOpening:
    def test_opens_after_threshold_failures(self) -> None:
        cb = _fast_cb(failure_threshold=3)
        for _ in range(3):
            try:
                with cb:
                    raise RuntimeError("fail")
            except RuntimeError:
                pass
        assert cb.state == CircuitBreakerState.OPEN

    def test_open_rejects_calls(self) -> None:
        cb = _fast_cb(failure_threshold=2)
        for _ in range(2):
            try:
                with cb:
                    raise RuntimeError("fail")
            except RuntimeError:
                pass
        with pytest.raises(CircuitOpenError):
            with cb:
                pass

    def test_rejected_calls_counted(self) -> None:
        cb = _fast_cb(failure_threshold=2)
        for _ in range(2):
            try:
                with cb:
                    raise RuntimeError("fail")
            except RuntimeError:
                pass
        for _ in range(3):
            try:
                with cb:
                    pass
            except CircuitOpenError:
                pass
        assert cb.stats().total_rejected == 3

    def test_open_still_counts_total_calls(self) -> None:
        cb = _fast_cb(failure_threshold=2)
        for _ in range(2):
            try:
                with cb:
                    raise RuntimeError()
            except RuntimeError:
                pass
        try:
            with cb:
                pass
        except CircuitOpenError:
            pass
        assert cb.stats().total_calls == 3


class TestCircuitBreakerHalfOpen:
    def test_transitions_to_half_open_after_timeout(self) -> None:
        cb = _fast_cb(failure_threshold=2, recovery_timeout_s=0.01)
        for _ in range(2):
            try:
                with cb:
                    raise RuntimeError()
            except RuntimeError:
                pass
        time.sleep(0.02)
        # Accessing state triggers transition check
        assert cb.state == CircuitBreakerState.HALF_OPEN

    def test_half_open_success_closes(self) -> None:
        cb = _fast_cb(failure_threshold=2, recovery_timeout_s=0.01)
        for _ in range(2):
            try:
                with cb:
                    raise RuntimeError()
            except RuntimeError:
                pass
        time.sleep(0.02)
        with cb:  # success in HALF_OPEN
            pass
        assert cb.state == CircuitBreakerState.CLOSED

    def test_half_open_failure_reopens(self) -> None:
        cb = _fast_cb(failure_threshold=2, recovery_timeout_s=0.01)
        for _ in range(2):
            try:
                with cb:
                    raise RuntimeError()
            except RuntimeError:
                pass
        time.sleep(0.02)
        try:
            with cb:
                raise RuntimeError("still broken")
        except RuntimeError:
            pass
        assert cb.state == CircuitBreakerState.OPEN


class TestCircuitBreakerReset:
    def test_reset_closes_open_circuit(self) -> None:
        cb = _fast_cb(failure_threshold=2)
        for _ in range(2):
            try:
                with cb:
                    raise RuntimeError()
            except RuntimeError:
                pass
        assert cb.is_open
        cb.reset()
        assert cb.is_closed

    def test_reset_clears_failure_count(self) -> None:
        cb = _fast_cb(failure_threshold=5)
        for _ in range(3):
            try:
                with cb:
                    raise RuntimeError()
            except RuntimeError:
                pass
        cb.reset()
        assert cb.stats().failure_count == 0

    def test_normal_after_reset(self) -> None:
        cb = _fast_cb(failure_threshold=2)
        for _ in range(2):
            try:
                with cb:
                    raise RuntimeError()
            except RuntimeError:
                pass
        cb.reset()
        with cb:  # should not raise
            pass
        assert cb.is_closed


class TestCircuitBreakerWindowExpiry:
    def test_old_failures_pruned(self) -> None:
        cb = _fast_cb(failure_threshold=3, failure_window_s=0.01)
        for _ in range(2):
            try:
                with cb:
                    raise RuntimeError()
            except RuntimeError:
                pass
        time.sleep(0.02)
        # Force prune via success
        with cb:
            pass
        assert cb.stats().failure_count == 0
        assert cb.is_closed


class TestGetCircuitBreaker:
    def test_singleton_per_name(self) -> None:
        cb1 = get_circuit_breaker("svc_a")
        cb2 = get_circuit_breaker("svc_a")
        assert cb1 is cb2

    def test_different_names_different_instances(self) -> None:
        cb1 = get_circuit_breaker("svc_x")
        cb2 = get_circuit_breaker("svc_y")
        assert cb1 is not cb2

    def test_returns_circuit_breaker(self) -> None:
        cb = get_circuit_breaker("svc_z")
        assert isinstance(cb, CircuitBreaker)
