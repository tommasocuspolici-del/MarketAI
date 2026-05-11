"""Tests for shared.error_budget."""
from __future__ import annotations

import time

from shared.error_budget import ErrorBudget


class TestErrorBudget:
    def test_initial_state_not_tripped(self) -> None:
        eb = ErrorBudget(window_minutes=5, threshold_pct=10.0)
        assert not eb.is_tripped

    def test_all_successes_stays_operational(self) -> None:
        eb = ErrorBudget(window_minutes=5, threshold_pct=10.0)
        for _ in range(20):
            eb.record_success()
        status = eb.status()
        assert status.error_rate_pct == 0.0
        assert not status.tripped

    def test_trips_when_threshold_exceeded(self) -> None:
        eb = ErrorBudget(window_minutes=5, threshold_pct=10.0)
        # 5 successi + 2 errori = 28.6% > 10%
        for _ in range(5):
            eb.record_success()
        for _ in range(2):
            eb.record_error()
        assert eb.is_tripped

    def test_does_not_trip_below_threshold(self) -> None:
        eb = ErrorBudget(window_minutes=5, threshold_pct=10.0)
        # 95 successi + 5 errori = 5% < 10%
        for _ in range(95):
            eb.record_success()
        for _ in range(5):
            eb.record_error()
        assert not eb.is_tripped

    def test_status_returns_accurate_counts(self) -> None:
        eb = ErrorBudget(window_minutes=5, threshold_pct=10.0)
        eb.record_success()
        eb.record_success()
        eb.record_error()
        status = eb.status()
        assert status.total_events == 3
        assert status.error_events == 1
        assert status.error_rate_pct == pytest_approx(33.33, rel=0.01)

    def test_reset_clears_state(self) -> None:
        eb = ErrorBudget(window_minutes=5, threshold_pct=1.0)
        for _ in range(5):
            eb.record_error()
        assert eb.is_tripped
        eb.reset()
        assert not eb.is_tripped
        assert eb.status().total_events == 0

    def test_events_expire_outside_window(self) -> None:
        # Finestra 1 minuto per test rapido — usiamo pochi eventi reali
        eb = ErrorBudget(window_minutes=1, threshold_pct=10.0)
        # Simuliamo errori "vecchi" manipolando direttamente gli eventi interni
        # via record normale, poi aspettiamo che cadano fuori finestra.
        eb.record_error()
        eb.record_error()
        # Hack: forziamo il timestamp degli eventi a un istante lontano
        for ev in eb._events:
            ev.ts = time.monotonic() - 120  # 2 minuti fa
        # La prossima lettura deve vedere zero eventi dentro la finestra
        assert eb.status().total_events == 0
        assert not eb.is_tripped


def pytest_approx(value: float, rel: float) -> object:
    """Tiny helper to avoid import in body."""
    import pytest

    return pytest.approx(value, rel=rel)
