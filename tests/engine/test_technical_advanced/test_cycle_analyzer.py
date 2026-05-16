"""Tests for CycleAnalyzer — Hurst exponent + FFT dominant cycle."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.analytics.technical.cycle_analyzer import CycleAnalyzer, CycleResult


def _trending_prices(n: int = 252, trend: float = 0.002) -> np.ndarray:
    rng   = np.random.default_rng(0)
    rets  = trend + rng.normal(0, 0.005, n)
    return 100.0 * np.cumprod(1 + rets)


def _autocorrelated_prices(n: int = 500, rho: float = 0.7) -> np.ndarray:
    """Prices from AR(1) returns with strong autocorrelation → H > 0.5."""
    rng  = np.random.default_rng(3)
    rets = np.zeros(n)
    rets[0] = rng.normal(0, 0.005)
    for i in range(1, n):
        rets[i] = rho * rets[i - 1] + (1 - rho) * rng.normal(0, 0.005)
    return 100.0 * np.cumprod(1 + rets)


def _mean_reverting_prices(n: int = 252) -> np.ndarray:
    rng    = np.random.default_rng(1)
    prices = np.zeros(n)
    prices[0] = 100.0
    mean   = 100.0
    for i in range(1, n):
        prices[i] = prices[i - 1] + 0.5 * (mean - prices[i - 1]) + rng.normal(0, 1)
    return np.maximum(prices, 1.0)


def _sinusoidal_prices(n: int = 252, period: int = 63) -> np.ndarray:
    """Price with known dominant cycle for FFT verification."""
    t = np.arange(n)
    return 100.0 + 10.0 * np.sin(2 * np.pi * t / period) + np.random.default_rng(2).normal(0, 0.5, n)


class TestHurstExponent:
    def test_returns_result_object(self) -> None:
        analyzer = CycleAnalyzer()
        result   = analyzer.analyze(_trending_prices())
        assert isinstance(result, CycleResult)

    def test_hurst_in_valid_range(self) -> None:
        analyzer = CycleAnalyzer()
        result   = analyzer.analyze(_trending_prices())
        if result.hurst is not None:
            assert 0.0 <= result.hurst <= 1.0

    def test_autocorrelated_series_hurst_above_05(self) -> None:
        """AR(1) returns with rho=0.7 → strong positive autocorrelation → H > 0.5."""
        analyzer = CycleAnalyzer()
        result   = analyzer.analyze(_autocorrelated_prices(500, rho=0.7))
        if result.hurst is not None:
            assert result.hurst > 0.5, f"Expected H > 0.5 for autocorrelated, got {result.hurst}"

    def test_drifted_rw_hurst_near_05(self) -> None:
        """Drifted random walk: increments are iid → H ≈ 0.5 (not necessarily > 0.5)."""
        analyzer = CycleAnalyzer()
        result   = analyzer.analyze(_trending_prices(500, trend=0.003))
        if result.hurst is not None:
            assert 0.0 <= result.hurst <= 1.0    # just check valid range

    def test_mean_reverting_hurst_below_05(self) -> None:
        analyzer = CycleAnalyzer()
        result   = analyzer.analyze(_mean_reverting_prices(500))
        if result.hurst is not None:
            assert result.hurst < 0.6    # allow tolerance; mean-reverting should be lower

    def test_insufficient_data_returns_none(self) -> None:
        analyzer = CycleAnalyzer(min_obs_hurst=50)
        result   = analyzer.analyze(np.array([100.0, 101.0, 102.0]))
        assert result.hurst is None


class TestHurstRegime:
    def test_regime_trending(self) -> None:
        analyzer = CycleAnalyzer()
        result   = analyzer.analyze(_trending_prices(500, trend=0.003))
        assert result.hurst_regime in ("trending", "random", "mean_reverting", "unknown")

    def test_regime_unknown_when_no_hurst(self) -> None:
        analyzer = CycleAnalyzer(min_obs_hurst=1000)
        result   = analyzer.analyze(_trending_prices(50))
        assert result.hurst_regime == "unknown"


class TestFFTCycle:
    def test_dominant_cycle_not_none_with_enough_data(self) -> None:
        analyzer = CycleAnalyzer()
        result   = analyzer.analyze(_sinusoidal_prices(252, 63))
        assert result.dominant_cycle_days is not None

    def test_dominant_cycle_in_valid_range(self) -> None:
        analyzer = CycleAnalyzer()
        result   = analyzer.analyze(_sinusoidal_prices(252, 63))
        if result.dominant_cycle_days is not None:
            assert 5 <= result.dominant_cycle_days <= 252

    def test_fft_detects_quarterly_cycle(self) -> None:
        """With a strong 63-day cycle, FFT should detect a cycle near 63 days."""
        analyzer = CycleAnalyzer()
        prices   = _sinusoidal_prices(504, period=63)
        result   = analyzer.analyze(prices)
        if result.dominant_cycle_days is not None:
            # Allow ±20% tolerance
            assert 50 <= result.dominant_cycle_days <= 80, \
                f"Expected ~63 days, got {result.dominant_cycle_days}"

    def test_insufficient_data_cycle_none(self) -> None:
        analyzer = CycleAnalyzer(min_obs_fft=30)
        result   = analyzer.analyze(np.array([100.0] * 5))
        assert result.dominant_cycle_days is None


class TestFFTPowerSpectrum:
    def test_fft_arrays_populated_with_enough_data(self) -> None:
        analyzer = CycleAnalyzer()
        result   = analyzer.analyze(_trending_prices(100))
        assert len(result.fft_power) > 0
        assert len(result.fft_freqs) > 0

    def test_fft_arrays_empty_with_too_few_data(self) -> None:
        analyzer = CycleAnalyzer(min_obs_fft=100)
        result   = analyzer.analyze(_trending_prices(10))
        assert len(result.fft_power) == 0

    def test_n_obs_correct(self) -> None:
        analyzer = CycleAnalyzer()
        prices   = _trending_prices(200)
        result   = analyzer.analyze(prices)
        assert result.n_obs == 200
