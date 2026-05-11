"""Tests for personal.wealth_scenarios."""
from __future__ import annotations

import time

import numpy as np
import pytest

from personal.wealth_scenarios import (
    FIREResult,
    RetirementSimulator,
    WealthSimulationResult,
    WealthSimulator,
)
from shared.exceptions import PersonalError


# ═══════════════════════════════════════════════════════════════════════════
# WealthSimulator
# ═══════════════════════════════════════════════════════════════════════════
class TestWealthSimulator:
    def test_basic_simulation(self) -> None:
        sim = WealthSimulator()
        result = sim.simulate(
            initial_wealth=10_000.0,
            monthly_savings=500.0,
            annual_return_mean=0.07,
            annual_return_std=0.15,
            years=10,
            n_simulations=1_000,
            seed=42,
        )
        assert isinstance(result, WealthSimulationResult)
        assert len(result.percentile_50) == 121   # 10 anni * 12 + 1 (t=0)
        # Mediano deve essere maggiore del valore iniziale (con risparmio + rendimento)
        assert result.final_p50 > result.initial_wealth

    def test_percentile_ordering(self) -> None:
        sim = WealthSimulator()
        result = sim.simulate(
            initial_wealth=10_000.0,
            monthly_savings=500.0,
            annual_return_mean=0.07,
            annual_return_std=0.15,
            years=10,
            n_simulations=1_000,
            seed=42,
        )
        # P10 ≤ P50 ≤ P90 sempre
        assert (result.percentile_10 <= result.percentile_50).all()
        assert (result.percentile_50 <= result.percentile_90).all()

    def test_real_terms_smaller_than_nominal(self) -> None:
        sim = WealthSimulator()
        result_real = sim.simulate(
            initial_wealth=10_000.0, monthly_savings=500.0,
            annual_return_mean=0.07, annual_return_std=0.15,
            years=20, n_simulations=500, real_terms=True, seed=42,
        )
        result_nominal = sim.simulate(
            initial_wealth=10_000.0, monthly_savings=500.0,
            annual_return_mean=0.07, annual_return_std=0.15,
            years=20, n_simulations=500, real_terms=False, seed=42,
        )
        # Real terms ≤ nominal (deflation)
        assert result_real.final_p50 < result_nominal.final_p50

    def test_zero_savings_only_growth(self) -> None:
        sim = WealthSimulator()
        result = sim.simulate(
            initial_wealth=10_000.0, monthly_savings=0.0,
            annual_return_mean=0.07, annual_return_std=0.10,
            years=10, n_simulations=500, real_terms=False, seed=42,
        )
        # Con solo growth (no save), median ~ 10k * (1.07)^10 ≈ 19.7k
        assert 12_000 < result.final_p50 < 30_000

    def test_invalid_inputs_raise(self) -> None:
        sim = WealthSimulator()
        with pytest.raises(PersonalError, match="initial_wealth"):
            sim.simulate(
                initial_wealth=-100.0, monthly_savings=500,
                annual_return_mean=0.07, annual_return_std=0.15, years=10,
            )
        with pytest.raises(PersonalError, match="years"):
            sim.simulate(
                initial_wealth=1000, monthly_savings=100,
                annual_return_mean=0.07, annual_return_std=0.15, years=100,
            )
        with pytest.raises(PersonalError, match="n_simulations"):
            sim.simulate(
                initial_wealth=1000, monthly_savings=100,
                annual_return_mean=0.07, annual_return_std=0.15, years=10,
                n_simulations=10,
            )

    def test_deterministic_with_seed(self) -> None:
        sim = WealthSimulator()
        r1 = sim.simulate(
            initial_wealth=10_000, monthly_savings=500,
            annual_return_mean=0.07, annual_return_std=0.15,
            years=5, n_simulations=500, seed=123,
        )
        r2 = sim.simulate(
            initial_wealth=10_000, monthly_savings=500,
            annual_return_mean=0.07, annual_return_std=0.15,
            years=5, n_simulations=500, seed=123,
        )
        # Stesso seed → stessi risultati esatti
        np.testing.assert_array_equal(r1.percentile_50, r2.percentile_50)


# ═══════════════════════════════════════════════════════════════════════════
# Performance benchmark — DoD Fase 6: 10k sim < 3s
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.benchmark
class TestPerformance:
    def test_10k_simulations_under_3s(self) -> None:
        """DoD Fase 6: Monte Carlo 10k sim < 3s."""
        sim = WealthSimulator()
        t0 = time.monotonic()
        result = sim.simulate(
            initial_wealth=50_000.0,
            monthly_savings=1_000.0,
            annual_return_mean=0.07,
            annual_return_std=0.15,
            years=20,
            n_simulations=10_000,
            seed=42,
        )
        elapsed = time.monotonic() - t0

        assert result.n_simulations == 10_000
        # DoD: < 3s
        assert elapsed < 3.0, f"expected <3s, got {elapsed:.2f}s"


# ═══════════════════════════════════════════════════════════════════════════
# RetirementSimulator
# ═══════════════════════════════════════════════════════════════════════════
class TestRetirementSimulator:
    def test_fire_calculation(self) -> None:
        sim = RetirementSimulator()
        result = sim.find_fire_age(
            current_age=30,
            annual_expenses=30_000.0,
            initial_wealth=50_000.0,
            monthly_savings=2_000.0,
            annual_return_mean=0.07,
            annual_return_std=0.15,
            years_horizon=40,
            n_simulations=1_000,
            seed=42,
        )
        assert isinstance(result, FIREResult)
        # Target = 30k / 0.04 = 750k
        assert result.target_wealth == 750_000.0

    def test_fire_unreachable_returns_none(self) -> None:
        sim = RetirementSimulator()
        result = sim.find_fire_age(
            current_age=60,
            annual_expenses=200_000.0,   # Target enorme: 5M
            initial_wealth=10_000.0,
            monthly_savings=500.0,
            annual_return_mean=0.05,
            annual_return_std=0.10,
            years_horizon=10,             # Orizzonte breve
            n_simulations=500,
            seed=42,
        )
        assert result.fire_age is None
        assert result.years_to_fire is None
        assert result.probability == 0.0

    def test_invalid_age_raises(self) -> None:
        sim = RetirementSimulator()
        with pytest.raises(PersonalError, match="current_age"):
            sim.find_fire_age(
                current_age=10, annual_expenses=20_000,
                initial_wealth=1_000, monthly_savings=100,
                annual_return_mean=0.05, annual_return_std=0.10,
            )

    def test_invalid_withdrawal_rate_raises(self) -> None:
        sim = RetirementSimulator()
        with pytest.raises(PersonalError, match="withdrawal_rate"):
            sim.find_fire_age(
                current_age=30, annual_expenses=20_000,
                initial_wealth=1_000, monthly_savings=100,
                annual_return_mean=0.05, annual_return_std=0.10,
                withdrawal_rate=0.50,  # 50% non realistico
            )
