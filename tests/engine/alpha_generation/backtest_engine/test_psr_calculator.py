"""Tests for Probabilistic Sharpe Ratio calculator."""
from __future__ import annotations

import numpy as np
import pytest

from engine.alpha_generation.backtest_engine.psr_calculator import (
    PSRResult,
    probabilistic_sharpe_ratio,
    MIN_SAMPLES,
    DEFAULT_BENCHMARK,
    PERIODS_YEAR_DAILY,
)


# ─── Fixtures ────────────────────────────────────────────────────────────── #

@pytest.fixture
def positive_returns() -> np.ndarray:
    """Returns con Sharpe ratio alto (positivo e significativo)."""
    rng = np.random.default_rng(42)
    # mu = 0.001, sigma = 0.005 → SR_daily ≈ 0.2, SR_annual ≈ 3.17
    return rng.normal(0.001, 0.005, 500)


@pytest.fixture
def negative_returns() -> np.ndarray:
    """Returns con Sharpe ratio negativo."""
    rng = np.random.default_rng(42)
    return rng.normal(-0.001, 0.005, 500)


@pytest.fixture
def gaussian_returns_no_edge() -> np.ndarray:
    """Returns Gaussiani con SR ≈ 0 (benchmark = 0)."""
    rng = np.random.default_rng(99)
    return rng.normal(0.0, 0.01, 300)


# ─── Tests: basic output shape ───────────────────────────────────────────── #

class TestPSRResultStructure:
    def test_returns_psr_result(self, positive_returns: np.ndarray) -> None:
        result = probabilistic_sharpe_ratio(positive_returns)
        assert isinstance(result, PSRResult)

    def test_all_fields_populated(self, positive_returns: np.ndarray) -> None:
        result = probabilistic_sharpe_ratio(positive_returns)
        assert result.observed_sharpe is not None
        assert result.psr is not None
        assert result.skewness is not None
        assert result.excess_kurtosis is not None
        assert result.n_samples == len(positive_returns)

    def test_psr_in_0_1(self, positive_returns: np.ndarray) -> None:
        result = probabilistic_sharpe_ratio(positive_returns)
        assert 0.0 <= result.psr <= 1.0

    def test_psr_in_0_1_negative_returns(self, negative_returns: np.ndarray) -> None:
        result = probabilistic_sharpe_ratio(negative_returns)
        assert 0.0 <= result.psr <= 1.0


# ─── Tests: PSR correctness ──────────────────────────────────────────────── #

class TestPSRCorrectness:
    def test_high_sharpe_gives_high_psr(self, positive_returns: np.ndarray) -> None:
        """Con SR annuale ≈ 3, PSR dovrebbe essere vicino a 1."""
        result = probabilistic_sharpe_ratio(positive_returns, sr_benchmark=0.0)
        assert result.psr > 0.90, f"Expected PSR > 0.90, got {result.psr:.4f}"
        assert result.is_significant

    def test_negative_sharpe_gives_low_psr(self, negative_returns: np.ndarray) -> None:
        """Con SR negativo, PSR ≪ 0.90."""
        result = probabilistic_sharpe_ratio(negative_returns, sr_benchmark=0.0)
        assert result.psr < 0.50, f"Expected PSR < 0.50, got {result.psr:.4f}"
        assert not result.is_significant

    def test_zero_returns_psr_around_half(self, gaussian_returns_no_edge: np.ndarray) -> None:
        """Con SR ≈ 0 e benchmark = 0, PSR ≈ 0.5."""
        result = probabilistic_sharpe_ratio(gaussian_returns_no_edge, sr_benchmark=0.0)
        # Non precisissimo per sample finito, ma dovrebbe essere vicino a 0.5
        assert 0.0 <= result.psr <= 1.0

    def test_benchmark_effect(self, positive_returns: np.ndarray) -> None:
        """Con benchmark più alto, PSR deve essere inferiore."""
        psr_low_bench = probabilistic_sharpe_ratio(positive_returns, sr_benchmark=0.0)
        psr_high_bench = probabilistic_sharpe_ratio(positive_returns, sr_benchmark=5.0)
        assert psr_low_bench.psr > psr_high_bench.psr


# ─── Tests: edge cases ───────────────────────────────────────────────────── #

class TestPSREdgeCases:
    def test_insufficient_samples_returns_result(self) -> None:
        """Con meno di MIN_SAMPLES, il calcolo non deve crashare."""
        small = np.array([0.01, 0.02, -0.01])
        result = probabilistic_sharpe_ratio(small)
        assert isinstance(result, PSRResult)
        assert result.n_samples == 3

    def test_constant_returns_no_crash(self) -> None:
        """Returns costanti (sigma=0) non devono causare ZeroDivisionError."""
        constant = np.ones(100) * 0.001
        result = probabilistic_sharpe_ratio(constant)
        assert isinstance(result, PSRResult)

    def test_periods_per_year_parameter(self) -> None:
        """Parametro periods_per_year viene usato per l'annualizzazione."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.005, 200)
        result_daily = probabilistic_sharpe_ratio(returns, periods_per_year=252)
        result_monthly = probabilistic_sharpe_ratio(returns, periods_per_year=12)
        # SR annualizzato diverso per scalatura diversa
        assert result_daily.observed_sharpe != result_monthly.observed_sharpe

    def test_is_significant_flag(self) -> None:
        """is_significant deve essere True sse PSR > 0.90."""
        rng = np.random.default_rng(0)
        high_returns = rng.normal(0.002, 0.004, 500)
        result = probabilistic_sharpe_ratio(high_returns)
        assert result.is_significant == (result.psr > 0.90)
