"""Capacity Estimator — stima capacità massima strategia in USD."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from shared.logger import get_logger
from shared.exceptions import BacktestError

log = get_logger(__name__)

PARTICIPATION_RATE: float = 0.05   # 5% volume giornaliero
_CAPACITY_WARNING_THRESHOLD: float = 0.10  # 10% della capacità → warning


@dataclass
class CapacityResult:
    ticker: str
    adtv_usd: float            # Average Daily Trading Volume in USD
    turnover_daily: float      # Turnover giornaliero della strategia
    capacity_usd: float        # ADTV * participation_rate / turnover
    capacity_warning: bool     # True if capital > 0.1 * capacity


class CapacityEstimator:
    """Stima la capacità massima di una strategia rispetto all'ADTV.

    Formula: capacity = ADTV_USD * participation_rate / turnover_daily

    Il turnover_daily rappresenta la frazione del portafoglio che viene
    ribilanciata ogni giorno (es. 0.10 = 10% giornaliero).
    """

    def __init__(self, participation_rate: float = PARTICIPATION_RATE) -> None:
        if not (0.0 < participation_rate <= 1.0):
            raise BacktestError(
                f"participation_rate must be in (0, 1], got {participation_rate}"
            )
        self._participation_rate = participation_rate

    # ------------------------------------------------------------------ #
    # Single asset                                                         #
    # ------------------------------------------------------------------ #

    def estimate(
        self,
        ticker: str,
        adtv_usd: float,
        daily_turnover: float,
        current_capital_usd: float = 0.0,
    ) -> CapacityResult:
        """Stima la capacità per un singolo asset.

        Args:
            ticker:              Simbolo dell'asset.
            adtv_usd:            Average Daily Trading Volume in USD.
            daily_turnover:      Frazione [0,1] del portafoglio negoziata giornalmente.
            current_capital_usd: Capitale corrente (per calcolare capacity_warning).

        Returns:
            CapacityResult con capacità stimata e flag di warning.
        """
        if adtv_usd < 0.0:
            raise BacktestError(f"adtv_usd must be non-negative, got {adtv_usd}")
        if not (0.0 <= daily_turnover <= 1.0):
            raise BacktestError(f"daily_turnover must be in [0, 1], got {daily_turnover}")

        if daily_turnover <= 0.0:
            # Turnover zero → capacità infinita
            capacity = float("inf")
        else:
            capacity = adtv_usd * self._participation_rate / daily_turnover

        # Warning se il capitale corrente supera il 10% della capacità
        warning = (
            current_capital_usd > _CAPACITY_WARNING_THRESHOLD * capacity
            if capacity != float("inf")
            else False
        )

        log.debug(
            "capacity.estimated",
            ticker=ticker,
            adtv_usd=round(adtv_usd, 2),
            turnover=round(daily_turnover, 4),
            capacity_usd=round(capacity, 2) if capacity != float("inf") else "inf",
            warning=warning,
        )

        return CapacityResult(
            ticker=ticker,
            adtv_usd=adtv_usd,
            turnover_daily=daily_turnover,
            capacity_usd=capacity,
            capacity_warning=warning,
        )

    # ------------------------------------------------------------------ #
    # Portfolio                                                            #
    # ------------------------------------------------------------------ #

    def estimate_portfolio(
        self,
        positions: dict[str, float],
        daily_turnover: float,
        current_capital_usd: float,
    ) -> dict[str, CapacityResult]:
        """Stima la capacità per ogni posizione del portafoglio.

        Args:
            positions:           Mappa ticker → ADTV in USD.
            daily_turnover:      Turnover giornaliero comune per tutte le posizioni.
            current_capital_usd: Capitale totale del portafoglio.

        Returns:
            Dizionario ticker → CapacityResult.
        """
        n = len(positions)
        if n == 0:
            return {}

        # Il capitale per ticker è il capitale totale diviso per il numero di posizioni
        capital_per_ticker = current_capital_usd / n if n > 0 else 0.0

        results: dict[str, CapacityResult] = {}
        for ticker, adtv in positions.items():
            results[ticker] = self.estimate(
                ticker=ticker,
                adtv_usd=adtv,
                daily_turnover=daily_turnover,
                current_capital_usd=capital_per_ticker,
            )

        n_warnings = sum(1 for r in results.values() if r.capacity_warning)
        log.info(
            "capacity.portfolio_estimated",
            n_tickers=n,
            n_warnings=n_warnings,
            total_capital=round(current_capital_usd, 2),
        )

        return results
