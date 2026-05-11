"""Retirement simulator — FIRE calculator + wealth target solver.

Computes the age at which a target wealth (e.g. 25x annual expenses, the
FIRE rule of thumb) is reached with a chosen savings strategy.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from personal.wealth_scenarios.simulator import (
    WealthSimulationResult,
    WealthSimulator,
)
from shared.exceptions import PersonalError
from shared.logger import get_logger

__version__ = "6.0.0"

__all__ = ["FIREResult", "RetirementSimulator"]

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class FIREResult:
    """Outcome of a FIRE (Financial Independence Retire Early) computation."""

    target_wealth: float
    fire_age: int | None        # None se non raggiungibile entro l'orizzonte
    years_to_fire: int | None
    probability: float          # Frazione di simulazioni che raggiunge il target
    base_simulation: WealthSimulationResult


class RetirementSimulator:
    """Wraps WealthSimulator with retirement-specific helpers."""

    def __init__(self, simulator: WealthSimulator | None = None) -> None:
        self._sim = simulator or WealthSimulator()

    def find_fire_age(
        self,
        current_age: int,
        annual_expenses: float,
        initial_wealth: float,
        monthly_savings: float,
        annual_return_mean: float,
        annual_return_std: float,
        years_horizon: int = 40,
        withdrawal_rate: float = 0.04,
        n_simulations: int = 10_000,
        seed: int | None = None,
    ) -> FIREResult:
        """Find the age at which FIRE target is reached (median scenario).

        FIRE target = annual_expenses / withdrawal_rate (default 4% rule).

        Args:
            current_age: Età attuale (anni).
            annual_expenses: Spese annuali correnti.
            initial_wealth: Patrimonio iniziale.
            monthly_savings: Risparmio mensile.
            annual_return_mean: Rendimento atteso annuo.
            annual_return_std: Volatilità annua.
            years_horizon: Orizzonte massimo simulazione.
            withdrawal_rate: Tasso prelievo annuo (default 4%).
            n_simulations: Numero simulazioni.
            seed: Seed RNG.

        Returns:
            FIREResult con fire_age (None se non raggiungibile in horizon).
        """
        if not 18 <= current_age <= 80:
            raise PersonalError(
                f"current_age must be in [18, 80], got {current_age}"
            )
        if annual_expenses <= 0:
            raise PersonalError(
                f"annual_expenses must be > 0, got {annual_expenses}"
            )
        if not 0.01 <= withdrawal_rate <= 0.10:
            raise PersonalError(
                f"withdrawal_rate must be in [1%, 10%], got {withdrawal_rate}"
            )

        target = annual_expenses / withdrawal_rate

        # Simulazione patrimonio in valori REALI (ipotesi: spese aumentano con inflazione)
        sim = self._sim.simulate(
            initial_wealth=initial_wealth,
            monthly_savings=monthly_savings,
            annual_return_mean=annual_return_mean,
            annual_return_std=annual_return_std,
            years=years_horizon,
            n_simulations=n_simulations,
            real_terms=True,
            seed=seed,
        )

        # Quando il P50 (mediano) raggiunge il target?
        median_path = sim.percentile_50
        # First index where median >= target (numpy)
        reached = median_path >= target
        if not reached.any():
            log.info(
                "fire.unreachable",
                target=target,
                horizon_years=years_horizon,
            )
            return FIREResult(
                target_wealth=target,
                fire_age=None,
                years_to_fire=None,
                probability=0.0,
                base_simulation=sim,
            )

        first_month = int(np.argmax(reached))
        years_to_fire = max(1, first_month // 12 + (1 if first_month % 12 else 0))
        fire_age = current_age + years_to_fire

        # Probabilità: frazione di sim che ALLA FINE supera il target
        # (più conservativo del solo P50)
        all_finals = self._final_distribution(
            initial_wealth, monthly_savings, annual_return_mean,
            annual_return_std, years_to_fire, n_simulations, seed,
        )
        probability = float((all_finals >= target).mean())

        log.info(
            "fire.computed",
            fire_age=fire_age,
            years_to_fire=years_to_fire,
            target=target,
            probability=round(probability, 3),
        )
        return FIREResult(
            target_wealth=target,
            fire_age=fire_age,
            years_to_fire=years_to_fire,
            probability=probability,
            base_simulation=sim,
        )

    # ─── Internals ──────────────────────────────────────────────────────
    def _final_distribution(
        self,
        initial_wealth: float,
        monthly_savings: float,
        ann_ret_mean: float,
        ann_ret_std: float,
        years: int,
        n_simulations: int,
        seed: int | None,
    ) -> np.ndarray:
        """Run a fresh simulation and return the FULL distribution of the
        final-month wealth across all sims (used for probability)."""
        n_months = years * 12
        sigma = ann_ret_std / np.sqrt(12.0)
        mu_log = np.log(max(1.0 + ann_ret_mean / 12.0, 1e-9)) - 0.5 * sigma**2

        rng = np.random.default_rng(seed)
        returns = rng.lognormal(
            mean=mu_log, sigma=sigma, size=(n_simulations, n_months)
        )

        wealth = np.full(n_simulations, initial_wealth, dtype="float64")
        for t in range(n_months):
            wealth = wealth * returns[:, t] + monthly_savings

        return wealth
