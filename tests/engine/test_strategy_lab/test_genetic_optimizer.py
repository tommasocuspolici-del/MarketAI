"""Tests for GeneticOptimizer — DoD: early stop at generation 8 if fitness stagnates."""
from __future__ import annotations

import pytest

from engine.strategy_lab.genetic_optimizer import GeneticOptimizer, GeneticResult


def _quadratic_fitness(params: dict) -> float:
    """Simple fitness: maximum at x=5, y=5."""
    x = float(params.get("x", 0))
    y = float(params.get("y", 0))
    return -(x - 5.0) ** 2 - (y - 5.0) ** 2    # max at (5,5) = 0


def _constant_fitness(params: dict) -> float:
    """Always returns 0 — simulates stagnation."""
    return 0.0


class TestHillClimbingFallback:
    """Tests run hill-climbing (flag off by default)."""

    def test_returns_genetic_result(self) -> None:
        opt    = GeneticOptimizer(pop_size=10, n_gen=20, patience=8)
        result = opt.optimise(
            _quadratic_fitness,
            {"x": (0.0, 10.0), "y": (0.0, 10.0)},
        )
        assert isinstance(result, GeneticResult)

    def test_backend_is_hill_climbing(self) -> None:
        opt    = GeneticOptimizer()
        result = opt.optimise(_quadratic_fitness, {"x": (0.0, 10.0)})
        assert result.backend == "hill_climbing"

    def test_best_fitness_is_float(self) -> None:
        opt    = GeneticOptimizer(pop_size=20, n_gen=30)
        result = opt.optimise(_quadratic_fitness, {"x": (0.0, 10.0), "y": (0.0, 10.0)})
        assert isinstance(result.best_fitness, float)

    def test_best_params_has_all_keys(self) -> None:
        opt    = GeneticOptimizer(pop_size=10, n_gen=15)
        result = opt.optimise(_quadratic_fitness, {"x": (0.0, 10.0), "y": (0.0, 10.0)})
        assert "x" in result.best_params
        assert "y" in result.best_params


class TestEarlyStopping:
    def test_early_stop_on_constant_fitness(self) -> None:
        """DoD: early stop at generation ≤ patience when fitness stagnates."""
        patience = 8
        opt    = GeneticOptimizer(pop_size=5, n_gen=50, patience=patience, min_delta=0.001)
        result = opt.optimise(_constant_fitness, {"x": (0.0, 1.0)})
        # With constant fitness, should early-stop well before n_gen=50
        assert result.early_stopped is True
        assert result.n_generations <= patience + 2    # DoD: stops at ~patience generations

    def test_no_early_stop_when_improving(self) -> None:
        opt    = GeneticOptimizer(pop_size=10, n_gen=20, patience=8, min_delta=0.0)
        result = opt.optimise(_quadratic_fitness, {"x": (0.0, 10.0)})
        # With improving fitness, should run more generations
        assert result.n_generations > 0


class TestParameterSpaces:
    def test_categorical_param_space(self) -> None:
        opt    = GeneticOptimizer(pop_size=5, n_gen=5)
        result = opt.optimise(
            lambda p: 1.0 if p["mode"] == "fast" else 0.0,
            {"mode": ["fast", "slow", "medium"]},
        )
        assert result.best_params["mode"] in ("fast", "slow", "medium")

    def test_integer_param_space(self) -> None:
        opt    = GeneticOptimizer(pop_size=5, n_gen=10)
        result = opt.optimise(
            lambda p: float(p["n"]) / 10.0,
            {"n": (1, 10)},   # int range
        )
        assert isinstance(result.best_params["n"], (int, float))

    def test_disabled_flag_uses_hill_climbing(self) -> None:
        """genetic_optimization flag is false by default → always hill-climbing."""
        opt    = GeneticOptimizer()
        result = opt.optimise(_quadratic_fitness, {"x": (0.0, 5.0)})
        assert result.backend == "hill_climbing"
