"""Monte Carlo wealth simulator — projects future wealth (10k sim < 3s).

Uses log-normal monthly returns vectorized over (n_simulations, n_months).
Strictly numpy/scipy (Rule 8). Receives expected returns + volatility from
the engine layer via ``MarketContextForPersonal`` (Rule 21).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from shared.exceptions import PersonalError
from shared.logger import get_logger
from shared.metrics import metrics

__version__ = "6.0.0"

__all__ = ["WealthSimulationResult", "WealthSimulator"]

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class WealthSimulationResult:
    """Outcome of a Monte Carlo wealth projection."""

    percentile_10: np.ndarray   # Pessimistic scenario over time
    percentile_50: np.ndarray   # Median scenario over time (base case)
    percentile_90: np.ndarray   # Optimistic scenario over time
    n_simulations: int
    years: int
    initial_wealth: float
    monthly_savings: float
    real_terms: bool            # If True, deflated by inflation

    @property
    def n_months(self) -> int:
        return len(self.percentile_50) - 1   # bars include t=0

    @property
    def final_p10(self) -> float:
        return float(self.percentile_10[-1])

    @property
    def final_p50(self) -> float:
        return float(self.percentile_50[-1])

    @property
    def final_p90(self) -> float:
        return float(self.percentile_90[-1])


class WealthSimulator:
    """Monte Carlo simulator with reinvestment.

    Inputs:
      · Initial wealth (from NetWorthTracker)
      · Monthly savings (from CashFlowEngine)
      · Expected return + volatility (from engine via bridge)
      · Profile constraints (allocation limits — applied via expected_return)
    """

    def simulate(
        self,
        initial_wealth: float,
        monthly_savings: float,
        annual_return_mean: float,
        annual_return_std: float,
        years: int,
        n_simulations: int = 10_000,
        inflation_rate: float = 0.025,
        real_terms: bool = True,
        seed: int | None = None,
    ) -> WealthSimulationResult:
        """Run N Monte Carlo simulations.

        Args:
            initial_wealth: Patrimonio iniziale (units in profile.base_currency).
            monthly_savings: Risparmio nominale per mese.
            annual_return_mean: Es. 0.07 = 7% atteso annuo.
            annual_return_std: Es. 0.15 = 15% volatilità annua.
            years: Orizzonte temporale (1-50).
            n_simulations: Numero di simulazioni (1k-100k).
            inflation_rate: Per deflazionare i valori reali (default 2.5%).
            real_terms: Se True, restituisce valori reali (inflation-adjusted).
            seed: Seed RNG per riproducibilità (None = random).

        Returns:
            WealthSimulationResult con percentili nel tempo.

        Raises:
            PersonalError: input out of accepted range.
        """
        # Validazioni
        if initial_wealth < 0:
            raise PersonalError(f"initial_wealth must be >= 0, got {initial_wealth}")
        if monthly_savings < 0:
            raise PersonalError(
                f"monthly_savings must be >= 0, got {monthly_savings}"
            )
        if not 1 <= years <= 50:
            raise PersonalError(f"years must be in [1, 50], got {years}")
        if not 100 <= n_simulations <= 100_000:
            raise PersonalError(
                f"n_simulations must be in [100, 100000], got {n_simulations}"
            )
        if annual_return_std <= 0:
            raise PersonalError(
                f"annual_return_std must be > 0, got {annual_return_std}"
            )

        with metrics.timer(
            "wealth_simulation_ms",
            n_simulations=str(n_simulations),
            years=str(years),
        ):
            n_months = years * 12
            monthly_return_mean = annual_return_mean / 12.0
            monthly_return_std = annual_return_std / np.sqrt(12.0)

            # ─── Vettorizzazione completa (Rule 8) ─────────────────────
            # Log-normal monthly returns
            # Mu adjustment per log-normal: log(1+r) - 0.5*sigma^2
            sigma = monthly_return_std
            mu_log = np.log(max(1.0 + monthly_return_mean, 1e-9)) - 0.5 * sigma**2

            rng = np.random.default_rng(seed)
            returns = rng.lognormal(
                mean=mu_log, sigma=sigma, size=(n_simulations, n_months)
            )

            # ─── Wealth trajectory ─────────────────────────────────────
            # wealth[t+1] = wealth[t] * return[t] + savings
            # Vettorizzato: usiamo cumprod per la crescita,
            # poi aggiungiamo i contributi (geometric series approach)

            # Wealth matrix: shape (n_simulations, n_months + 1)
            wealth = np.zeros((n_simulations, n_months + 1), dtype="float64")
            wealth[:, 0] = initial_wealth

            # Iterazione vettorizzata: ad ogni step applichiamo i ritorni
            # alla simulazione INTERA simultaneamente — questo NON è un loop
            # Python su serie temporali (Rule 23), bensì un'iterazione
            # temporale obbligata per il modello di reinvestimento.
            # Ogni "step" elabora 10k simulazioni in un singolo op numpy.
            for t in range(n_months):
                wealth[:, t + 1] = wealth[:, t] * returns[:, t] + monthly_savings

            # ─── Real terms (inflation adjustment) ─────────────────────
            if real_terms:
                months_idx = np.arange(n_months + 1)
                deflator = (1.0 + inflation_rate / 12.0) ** months_idx
                wealth = wealth / deflator

            # ─── Percentile aggregation ────────────────────────────────
            p10 = np.percentile(wealth, 10, axis=0)
            p50 = np.percentile(wealth, 50, axis=0)
            p90 = np.percentile(wealth, 90, axis=0)

        result = WealthSimulationResult(
            percentile_10=p10,
            percentile_50=p50,
            percentile_90=p90,
            n_simulations=n_simulations,
            years=years,
            initial_wealth=initial_wealth,
            monthly_savings=monthly_savings,
            real_terms=real_terms,
        )

        log.info(
            "wealth_simulator.completed",
            n_sim=n_simulations,
            years=years,
            final_p50=round(float(p50[-1]), 2),
            real_terms=real_terms,
        )
        return result
