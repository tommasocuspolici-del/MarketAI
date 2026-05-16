"""Tests for shared.alpha_decay_monitor — AlphaDecayMonitor (QC-2)."""
from __future__ import annotations

import pytest

from shared.alpha_decay_monitor import (
    IC_MIN_THRESHOLD,
    IC_SOFT_WARNING,
    AlphaDecayMonitor,
)


def _fill_monitor(
    monitor: AlphaDecayMonitor,
    signal_name: str,
    n: int,
    signal_values: list[float] | None = None,
    forward_returns: list[float] | None = None,
) -> None:
    """Fill monitor with n correlated observations (default: positive IC ≈ 0.8)."""
    for i in range(n):
        sv = signal_values[i] if signal_values else float(i) / n
        fr = forward_returns[i] if forward_returns else sv + 0.01
        monitor.update(signal_name, signal_value=sv, forward_return=fr)


class TestObservationCount:
    def test_starts_at_zero(self) -> None:
        m = AlphaDecayMonitor()
        assert m.observation_count("x") == 0

    def test_increments(self) -> None:
        m = AlphaDecayMonitor()
        m.update("x", signal_value=0.5, forward_return=0.01)
        assert m.observation_count("x") == 1

    def test_multiple_signals_isolated(self) -> None:
        m = AlphaDecayMonitor()
        m.update("a", signal_value=0.5, forward_return=0.01)
        m.update("b", signal_value=0.5, forward_return=0.01)
        assert m.observation_count("a") == 1
        assert m.observation_count("b") == 1


class TestCheckDecayInsufficientData:
    def test_no_observations_returns_insufficient(self) -> None:
        m = AlphaDecayMonitor()
        ic, flag = m.check_decay("unknown_signal")
        assert ic is None
        assert flag == "insufficient_data"

    def test_few_observations_returns_insufficient(self) -> None:
        m = AlphaDecayMonitor()
        for i in range(5):
            m.update("x", signal_value=float(i), forward_return=float(i))
        ic, flag = m.check_decay("x")
        assert ic is None
        assert flag == "insufficient_data"

    def test_exactly_30_observations_computes(self) -> None:
        m = AlphaDecayMonitor()
        _fill_monitor(m, "x", 30)
        ic, flag = m.check_decay("x")
        assert ic is not None


class TestCheckDecayHighIC:
    def test_high_ic_returns_ok(self) -> None:
        m = AlphaDecayMonitor()
        _fill_monitor(m, "x", 50)    # perfect positive correlation → IC ≈ 1.0
        ic, flag = m.check_decay("x")
        assert ic is not None
        assert ic > IC_SOFT_WARNING
        assert flag == "ok"


class TestCheckDecayLowIC:
    def test_uncorrelated_signals_may_flag_low_ic(self) -> None:
        import random
        rng = random.Random(42)
        m = AlphaDecayMonitor()
        for _ in range(60):
            m.update("x", signal_value=rng.uniform(-1, 1), forward_return=rng.uniform(-1, 1))
        ic, _ = m.check_decay("x")
        # We just verify IC is computed; random IC could be anything
        assert ic is not None

    def test_negatively_correlated_gives_negative_ic(self) -> None:
        m = AlphaDecayMonitor()
        vals = [float(i) for i in range(50)]
        rets = [float(49 - i) for i in range(50)]  # perfect negative correlation
        _fill_monitor(m, "x", 50, signal_values=vals, forward_returns=rets)
        ic, _ = m.check_decay("x")
        assert ic is not None
        assert ic < 0


class TestGetWeightMultiplier:
    def test_no_observations_returns_full_weight(self) -> None:
        m = AlphaDecayMonitor()
        assert m.get_weight_multiplier("unknown") == pytest.approx(1.0)

    def test_insufficient_data_returns_full_weight(self) -> None:
        m = AlphaDecayMonitor()
        m.update("x", signal_value=0.5, forward_return=0.01)
        assert m.get_weight_multiplier("x") == pytest.approx(1.0)

    def test_high_ic_returns_full_weight(self) -> None:
        m = AlphaDecayMonitor()
        _fill_monitor(m, "x", 50)   # high positive IC
        mult = m.get_weight_multiplier("x")
        assert mult == pytest.approx(1.0)

    def test_thresholds_documented(self) -> None:
        assert IC_MIN_THRESHOLD == pytest.approx(0.02)
        assert IC_SOFT_WARNING  == pytest.approx(0.05)


class TestAllSignals:
    def test_empty(self) -> None:
        m = AlphaDecayMonitor()
        assert m.all_signals() == []

    def test_returns_tracked_names(self) -> None:
        m = AlphaDecayMonitor()
        m.update("a", signal_value=0.1, forward_return=0.01)
        m.update("b", signal_value=0.2, forward_return=0.02)
        assert set(m.all_signals()) == {"a", "b"}


class TestThreadSafety:
    def test_concurrent_updates(self) -> None:
        import threading
        m = AlphaDecayMonitor()
        errors: list[Exception] = []

        def worker() -> None:
            try:
                for i in range(20):
                    m.update("x", signal_value=float(i) / 20, forward_return=float(i) / 20)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert m.observation_count("x") <= 100   # maxlen=126 in default monitor
