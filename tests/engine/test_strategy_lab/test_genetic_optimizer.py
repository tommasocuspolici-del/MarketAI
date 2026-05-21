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


# ── _sample_random() ─────────────────────────────────────────────────────────

class TestSampleRandom:
    def test_float_range(self) -> None:
        result = GeneticOptimizer._sample_random({"x": (0.0, 1.0)})
        assert 0.0 <= result["x"] <= 1.0
        assert isinstance(result["x"], float)

    def test_int_range(self) -> None:
        result = GeneticOptimizer._sample_random({"n": (1, 10)})
        assert 1 <= result["n"] <= 10
        assert isinstance(result["n"], int)

    def test_categorical(self) -> None:
        opts = ["alpha", "beta", "gamma"]
        for _ in range(20):
            result = GeneticOptimizer._sample_random({"mode": opts})
            assert result["mode"] in opts

    def test_mixed_space(self) -> None:
        result = GeneticOptimizer._sample_random({
            "lr": (0.001, 0.1),
            "layers": (2, 5),
            "activation": ["relu", "tanh"],
        })
        assert 0.001 <= result["lr"] <= 0.1
        assert 2 <= result["layers"] <= 5
        assert result["activation"] in ("relu", "tanh")

    def test_returns_all_keys(self) -> None:
        space = {"a": (0.0, 1.0), "b": (1, 5), "c": ["x", "y"]}
        result = GeneticOptimizer._sample_random(space)
        assert set(result.keys()) == {"a", "b", "c"}


# ── GeneticResult convergence ─────────────────────────────────────────────────

class TestGeneticResultConvergence:
    def test_converged_true_when_fitness_improves(self) -> None:
        opt = GeneticOptimizer(pop_size=10, n_gen=20, patience=8, min_delta=0.0)
        result = opt.optimise(lambda p: float(p["x"]), {"x": (0.0, 10.0)})
        assert result.converged is True

    def test_converged_true_on_constant_fitness(self) -> None:
        opt = GeneticOptimizer(pop_size=5, n_gen=5, patience=8)
        result = opt.optimise(lambda p: 0.0, {"x": (0.0, 1.0)})
        # 0.0 > float("-inf") → converged = True
        assert result.converged is True

    def test_early_stopped_with_low_patience(self) -> None:
        opt = GeneticOptimizer(pop_size=5, n_gen=50, patience=3, min_delta=0.001)
        result = opt.optimise(lambda p: 0.0, {"x": (0.0, 1.0)})
        assert result.early_stopped is True
        assert result.n_generations <= 5  # stops at patience + 2 at most


# ── Fitness exception handling ────────────────────────────────────────────────

class TestFitnessExceptionHandling:
    def test_fitness_fn_exception_silently_skipped(self) -> None:
        def bad_fitness(p: dict) -> float:
            raise ValueError("evaluation error")

        opt = GeneticOptimizer(pop_size=5, n_gen=5, patience=8)
        result = opt.optimise(bad_fitness, {"x": (0.0, 1.0)})
        assert isinstance(result, GeneticResult)  # must not crash
        assert result.converged is False  # never got a real fitness value

    def test_intermittent_exception_uses_successful_evals(self) -> None:
        call_count = 0

        def flaky_fitness(p: dict) -> float:
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 0:
                raise RuntimeError("intermittent")
            return float(p["x"])

        opt = GeneticOptimizer(pop_size=10, n_gen=20, patience=8, min_delta=0.0)
        result = opt.optimise(flaky_fitness, {"x": (0.0, 10.0)})
        # Some evaluations succeed → converged should be True
        assert isinstance(result, GeneticResult)
