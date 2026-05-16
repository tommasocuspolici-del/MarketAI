"""GeneticOptimizer — parameter evolution for strategy optimisation.

Feature-flagged: requires feature_flag "genetic_optimization" = true.
Primary implementation: uses DEAP if available, falls back to a numpy
hill-climbing (random restarts) which is simpler but still effective.

DEAP: pip install deap  (optional dependency)
Feature flag: genetic_optimization: false by default (computationally expensive).

Early stopping: halts at generation N if fitness improvement < min_delta
for patience consecutive generations.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from shared.feature_flags import is_enabled
from shared.logger import get_logger

__version__ = "10.0.0"

__all__ = [
    "GeneticResult",
    "GeneticOptimizer",
]

log = get_logger(__name__)

_DEFAULT_POP_SIZE    = 50
_DEFAULT_N_GEN       = 20
_DEFAULT_EARLY_STOP  = 8     # generations without improvement → stop
_DEFAULT_MIN_DELTA   = 0.001 # minimum fitness improvement


@dataclass
class GeneticResult:
    best_params:    dict[str, Any]
    best_fitness:   float
    n_generations:  int
    converged:      bool
    early_stopped:  bool
    backend:        str    # "deap" | "hill_climbing"


class GeneticOptimizer:
    """Parameter optimiser using genetic algorithms or hill-climbing fallback.

    Args:
        pop_size:    Population size (DEAP) or restart count (hill-climbing).
        n_gen:       Max generations.
        patience:    Generations without improvement before early stop (DoD ≤ 8).
        min_delta:   Minimum fitness improvement to reset patience counter.
    """

    def __init__(
        self,
        pop_size:  int   = _DEFAULT_POP_SIZE,
        n_gen:     int   = _DEFAULT_N_GEN,
        patience:  int   = _DEFAULT_EARLY_STOP,
        min_delta: float = _DEFAULT_MIN_DELTA,
    ) -> None:
        self._pop_size  = pop_size
        self._n_gen     = n_gen
        self._patience  = patience
        self._min_delta = min_delta

    def optimise(
        self,
        fitness_fn:  Callable[[dict[str, Any]], float],
        param_space: dict[str, tuple],
        # Each value: (min, max) for float params or list of options for categorical
    ) -> GeneticResult:
        """Optimise strategy parameters via genetic algorithm or hill-climbing.

        Args:
            fitness_fn:  fn(params) → float (higher is better, e.g. OOS Sharpe).
            param_space: {param_name: (min, max) | [option1, option2, ...]}.

        Returns:
            GeneticResult with best params and convergence info.
        """
        if not is_enabled("genetic_optimization"):
            log.info("genetic_optimizer.disabled", reason="feature flag off")
            return self._hill_climbing(fitness_fn, param_space)

        try:
            return self._deap_optimise(fitness_fn, param_space)
        except ImportError:
            log.warning("genetic_optimizer.deap_unavailable", fallback="hill_climbing")
            return self._hill_climbing(fitness_fn, param_space)

    # ── Hill-climbing fallback ─────────────────────────────────────────────

    def _hill_climbing(
        self,
        fitness_fn:  Callable[[dict[str, Any]], float],
        param_space: dict[str, tuple],
    ) -> GeneticResult:
        """Random restart hill-climbing — simple, effective, always available."""
        best_params: dict[str, Any] = {}
        best_fitness = float("-inf")
        no_improve   = 0
        gen          = 0
        early_stopped = False

        for gen in range(self._n_gen):
            # Sample a random point in the parameter space
            candidate = self._sample_random(param_space)
            try:
                fitness = float(fitness_fn(candidate))
            except Exception as exc:
                log.debug("genetic.eval_failed", error=str(exc))
                continue

            if fitness > best_fitness + self._min_delta:
                best_fitness = fitness
                best_params  = candidate
                no_improve   = 0
            else:
                no_improve  += 1

            if no_improve >= self._patience:
                early_stopped = True
                log.info("genetic.early_stop", gen=gen, best_fitness=round(best_fitness, 4))
                break

        log.info(
            "genetic.hill_climbing_done",
            n_gen=gen + 1,
            best_fitness=round(best_fitness, 4),
        )
        return GeneticResult(
            best_params   = best_params,
            best_fitness  = round(best_fitness, 4),
            n_generations = gen + 1,
            converged     = best_fitness > float("-inf"),
            early_stopped = early_stopped,
            backend       = "hill_climbing",
        )

    # ── DEAP path ─────────────────────────────────────────────────────────

    def _deap_optimise(
        self,
        fitness_fn:  Callable[[dict[str, Any]], float],
        param_space: dict[str, tuple],
    ) -> GeneticResult:
        from deap import algorithms, base, creator, tools  # type: ignore[import]

        param_names = list(param_space.keys())

        creator.create("FitnessMax", base.Fitness, weights=(1.0,))
        creator.create("Individual", list, fitness=creator.FitnessMax)

        toolbox = base.Toolbox()
        toolbox.register("individual", self._init_individual, creator.Individual, param_space)
        toolbox.register("population", tools.initRepeat, list, toolbox.individual)

        def evaluate(individual):
            params = {n: v for n, v in zip(param_names, individual)}
            try:
                return (float(fitness_fn(params)),)
            except Exception:
                return (float("-inf"),)

        toolbox.register("evaluate", evaluate)
        toolbox.register("mate",   tools.cxTwoPoint)
        toolbox.register("mutate", tools.mutGaussian, mu=0, sigma=0.1, indpb=0.2)
        toolbox.register("select", tools.selTournament, tournsize=3)

        pop  = toolbox.population(n=self._pop_size)
        best_fitness = float("-inf")
        no_improve   = 0
        early_stopped = False

        for gen in range(self._n_gen):
            pop, log_data = algorithms.eaSimple(
                pop, toolbox, cxpb=0.5, mutpb=0.2, ngen=1, verbose=False
            )
            top = tools.selBest(pop, 1)[0]
            f   = float(top.fitness.values[0])

            if f > best_fitness + self._min_delta:
                best_fitness = f
                no_improve   = 0
            else:
                no_improve  += 1

            if no_improve >= self._patience:
                early_stopped = True
                break

        top_ind = tools.selBest(pop, 1)[0]
        best_params = {n: v for n, v in zip(param_names, top_ind)}
        return GeneticResult(
            best_params   = best_params,
            best_fitness  = round(best_fitness, 4),
            n_generations = gen + 1,
            converged     = best_fitness > float("-inf"),
            early_stopped = early_stopped,
            backend       = "deap",
        )

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _sample_random(param_space: dict[str, tuple]) -> dict[str, Any]:
        params: dict[str, Any] = {}
        for name, spec in param_space.items():
            if isinstance(spec, (list, tuple)) and len(spec) == 2 and isinstance(spec[0], (int, float)):
                lo, hi = spec
                params[name] = random.uniform(lo, hi) if isinstance(lo, float) else random.randint(int(lo), int(hi))
            elif isinstance(spec, (list, tuple)):
                params[name] = random.choice(spec)
            else:
                params[name] = spec
        return params

    @staticmethod
    def _init_individual(IndClass, param_space: dict[str, tuple]):
        individual = []
        for spec in param_space.values():
            if isinstance(spec, (list, tuple)) and len(spec) == 2 and isinstance(spec[0], (int, float)):
                lo, hi = spec
                individual.append(random.uniform(float(lo), float(hi)))
            elif isinstance(spec, (list, tuple)):
                individual.append(random.choice(spec))
            else:
                individual.append(spec)
        return IndClass(individual)
