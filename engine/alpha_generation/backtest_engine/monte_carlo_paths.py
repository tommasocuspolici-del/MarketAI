"""Monte Carlo Path Simulator — 1000+ path con bootstrap a blocchi."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from shared.logger import get_logger

log = get_logger(__name__)

N_PATHS_DEFAULT: int = 1000
BLOCK_SIZE_DEFAULT: int = 21    # ~1 mese trading
CONFIDENCE_LEVELS: list[float] = [0.05, 0.25, 0.50, 0.75, 0.95]


@dataclass
class MCResult:
    n_paths: int
    horizon_days: int
    percentiles: dict[float, float]   # percentile → final return
    sharpe_distribution: np.ndarray   # Sharpe per ogni path
    max_drawdown_distribution: np.ndarray
    p_positive_return: float           # P(return > 0)
    var_95: float                      # -5th percentile of return distribution
    cvar_95: float                     # Mean of returns < var_95


class MonteCarloPathSimulator:
    """Bootstrap a blocchi per preservare autocorrelazione dei rendimenti."""

    def __init__(
        self,
        n_paths: int = N_PATHS_DEFAULT,
        block_size: int = BLOCK_SIZE_DEFAULT,
        seed: int | None = None,
    ) -> None:
        self._n_paths = n_paths
        self._block_size = block_size
        self._rng = np.random.default_rng(seed)

    # ------------------------------------------------------------------ #
    # Main simulation                                                      #
    # ------------------------------------------------------------------ #

    def simulate(
        self,
        historical_returns: np.ndarray,
        horizon_days: int,
    ) -> MCResult:
        """Simula `n_paths` percorsi di rendimento su `horizon_days` giorni.

        Args:
            historical_returns: Array 1D di rendimenti storici (non annualizzati).
            horizon_days:       Orizzonte di simulazione in giorni.

        Returns:
            MCResult con statistiche aggregate.
        """
        historical_returns = np.asarray(historical_returns, dtype=float)
        historical_returns = historical_returns[~np.isnan(historical_returns)]

        if len(historical_returns) < self._block_size:
            log.warning(
                "mc_simulator.insufficient_history",
                n=len(historical_returns),
                block_size=self._block_size,
            )
            # Fallback: GBM con stima parametrica
            return self._simulate_gbm(historical_returns, horizon_days)

        # Genera tutti i path con block bootstrap
        final_returns = np.empty(self._n_paths)
        sharpes = np.empty(self._n_paths)
        max_dds = np.empty(self._n_paths)

        for i in range(self._n_paths):
            path = self._block_bootstrap(historical_returns, horizon_days)
            cum_return = float(np.prod(1.0 + path) - 1.0)
            final_returns[i] = cum_return

            # Sharpe del path
            mu_p = float(np.mean(path))
            sigma_p = float(np.std(path, ddof=1)) if len(path) > 1 else 1e-8
            sharpes[i] = mu_p / sigma_p if sigma_p > 0.0 else 0.0

            # Max drawdown del path
            max_dds[i] = self._max_drawdown(path)

        # Statistiche aggregate
        percentiles = {
            level: float(np.percentile(final_returns, level * 100))
            for level in CONFIDENCE_LEVELS
        }
        p_positive = float(np.mean(final_returns > 0.0))
        var_95 = float(np.percentile(final_returns, 5))
        tail_mask = final_returns <= var_95
        cvar_95 = float(np.mean(final_returns[tail_mask])) if tail_mask.any() else var_95

        log.info(
            "mc_simulator.done",
            n_paths=self._n_paths,
            horizon_days=horizon_days,
            p_positive=round(p_positive, 4),
            var_95=round(var_95, 4),
        )

        return MCResult(
            n_paths=self._n_paths,
            horizon_days=horizon_days,
            percentiles=percentiles,
            sharpe_distribution=sharpes,
            max_drawdown_distribution=max_dds,
            p_positive_return=p_positive,
            var_95=var_95,
            cvar_95=cvar_95,
        )

    # ------------------------------------------------------------------ #
    # Block bootstrap                                                      #
    # ------------------------------------------------------------------ #

    def _block_bootstrap(self, returns: np.ndarray, horizon: int) -> np.ndarray:
        """Genera un path con block bootstrap circolare.

        I blocchi contigui preservano l'autocorrelazione dei rendimenti.
        """
        n = len(returns)
        path: list[np.ndarray] = []
        days_generated = 0

        while days_generated < horizon:
            # Campiona un indice di inizio blocco uniformemente
            start = int(self._rng.integers(0, n))
            # Blocco circolare: wrap around se necessario
            remaining = horizon - days_generated
            block_len = min(self._block_size, remaining)

            indices = np.arange(start, start + block_len) % n
            path.append(returns[indices])
            days_generated += block_len

        return np.concatenate(path)

    # ------------------------------------------------------------------ #
    # GBM fallback                                                         #
    # ------------------------------------------------------------------ #

    def _simulate_gbm(self, returns: np.ndarray, horizon_days: int) -> MCResult:
        """Simulazione GBM parametrica quando lo storico è insufficiente."""
        mu = float(np.mean(returns)) if len(returns) > 0 else 0.0
        sigma = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.01

        # Genera tutti i path in una sola operazione
        noise = self._rng.normal(mu, sigma, (self._n_paths, horizon_days))
        final_returns = np.prod(1.0 + noise, axis=1) - 1.0

        path_sharpes = np.mean(noise, axis=1) / (np.std(noise, axis=1) + 1e-8)
        path_dds = np.array([self._max_drawdown(noise[i]) for i in range(self._n_paths)])

        percentiles = {
            level: float(np.percentile(final_returns, level * 100))
            for level in CONFIDENCE_LEVELS
        }
        p_positive = float(np.mean(final_returns > 0.0))
        var_95 = float(np.percentile(final_returns, 5))
        tail_mask = final_returns <= var_95
        cvar_95 = float(np.mean(final_returns[tail_mask])) if tail_mask.any() else var_95

        return MCResult(
            n_paths=self._n_paths,
            horizon_days=horizon_days,
            percentiles=percentiles,
            sharpe_distribution=path_sharpes,
            max_drawdown_distribution=path_dds,
            p_positive_return=p_positive,
            var_95=var_95,
            cvar_95=cvar_95,
        )

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _max_drawdown(returns: np.ndarray) -> float:
        """Calcola il maximum drawdown di una serie di rendimenti."""
        if len(returns) == 0:
            return 0.0
        cum_wealth = np.cumprod(1.0 + returns)
        running_max = np.maximum.accumulate(cum_wealth)
        drawdowns = (cum_wealth - running_max) / running_max
        return float(np.min(drawdowns))
