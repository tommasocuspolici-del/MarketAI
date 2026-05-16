"""Tests for custom_indicators.ic_tracker — CustomIndicatorICTracker."""
from __future__ import annotations

import numpy as np
import pytest

from custom_indicators.ic_tracker import CustomIndicatorICTracker
from shared.alpha_decay_monitor import AlphaDecayMonitor


class TestComputeIC:
    def test_perfect_positive_correlation_ic_one(self) -> None:
        monitor = AlphaDecayMonitor()
        tracker = CustomIndicatorICTracker(monitor)
        n = 50
        signals = np.arange(n, dtype=np.float64)
        returns = np.arange(n, dtype=np.float64)   # perfect correlation
        ic = tracker.compute_ic(signals, returns, "test_ind")
        assert ic == pytest.approx(1.0, abs=1e-6)   # DoD

    def test_perfect_negative_correlation(self) -> None:
        monitor = AlphaDecayMonitor()
        tracker = CustomIndicatorICTracker(monitor)
        n = 50
        signals = np.arange(n, dtype=np.float64)
        returns = np.arange(n - 1, -1, -1, dtype=np.float64)
        ic = tracker.compute_ic(signals, returns, "test_neg")
        assert ic == pytest.approx(-1.0, abs=1e-6)

    def test_insufficient_data_returns_nan(self) -> None:
        monitor = AlphaDecayMonitor()
        tracker = CustomIndicatorICTracker(monitor)
        signals = np.array([0.1, 0.2, 0.3])
        returns = np.array([0.01, 0.02, 0.03])
        ic = tracker.compute_ic(signals, returns, "tiny")
        assert np.isnan(ic)

    def test_mismatched_length_raises(self) -> None:
        monitor = AlphaDecayMonitor()
        tracker = CustomIndicatorICTracker(monitor)
        with pytest.raises(ValueError, match="same length"):
            tracker.compute_ic(np.ones(30), np.ones(20), "bad")

    def test_updates_alpha_decay_monitor(self) -> None:
        monitor = AlphaDecayMonitor()
        tracker = CustomIndicatorICTracker(monitor)
        n = 50
        signals = np.arange(n, dtype=np.float64) / n
        returns = np.arange(n, dtype=np.float64) / n
        tracker.compute_ic(signals, returns, "entry_window")
        assert monitor.observation_count("custom.entry_window") >= 1   # DoD


class TestBatchUpdate:
    def test_batch_feeds_monitor(self) -> None:
        monitor = AlphaDecayMonitor()
        tracker = CustomIndicatorICTracker(monitor)
        n = 30
        signals = np.linspace(0, 1, n)
        returns = np.linspace(0, 1, n)
        tracker.batch_update(signals, returns, "entry_window")
        assert monitor.observation_count("custom.entry_window") == n

    def test_batch_skips_nan(self) -> None:
        monitor = AlphaDecayMonitor()
        tracker = CustomIndicatorICTracker(monitor)
        signals = np.array([0.5, float("nan"), 0.3])
        returns = np.array([0.01, 0.02, 0.03])
        tracker.batch_update(signals, returns, "test")
        assert monitor.observation_count("custom.test") == 2
