"""Liquidity Analyzer — ADTV e giorni di liquidazione per ogni posizione.

La liquidità di mercato misura la facilità con cui un asset può essere
venduto senza impattare significativamente il prezzo.

Metodo: Average Daily Trading Volume (ADTV) × participation rate
Days to Liquidate = position_usd / (ADTV_usd × participation_rate)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from shared.logger import get_logger

__version__ = "11.0.0"

__all__ = ["LiquidityAnalyzer", "LiquidityResult"]

log = get_logger(__name__)

PARTICIPATION_RATE: float = 0.20    # 20% ADTV per giorno (limite market impact)
MIN_ADTV_SAMPLES: int = 20
ADTV_LOOKBACK_DAYS: int = 30
ILLIQUID_THRESHOLD_DAYS: float = 5.0   # > 5 giorni = illiquid
MAX_LIQUIDITY_SCORE_DAYS: float = 0.5  # ≤ 0.5 giorni = score = 1.0
MIN_LIQUIDITY_SCORE_DAYS: float = 30.0  # ≥ 30 giorni = score = 0.0


@dataclass
class LiquidityResult:
    """Risultato analisi liquidità per una singola posizione."""

    ticker: str
    adtv_shares: float         # Average Daily Trading Volume (shares)
    adtv_usd: float            # ADTV in USD
    position_usd: float        # Valore posizione in USD
    days_to_liquidate: float   # position_usd / (ADTV × participation_rate)
    liquidity_score: float     # [0,1]: 1=very liquid, 0=illiquid
    is_illiquid: bool          # True if days_to_liquidate > ILLIQUID_THRESHOLD_DAYS


class LiquidityAnalyzer:
    """Analisi liquidità portafoglio basata su ADTV.

    Calcola per ogni posizione:
    - ADTV (volumi medi giornalieri)
    - Giorni necessari per liquidare a participation rate del 20%
    - Liquidity score normalizzato [0,1]
    """

    def __init__(
        self,
        participation_rate: float = PARTICIPATION_RATE,
        adtv_lookback_days: int = ADTV_LOOKBACK_DAYS,
    ) -> None:
        self._participation_rate = participation_rate
        self._lookback = adtv_lookback_days

    def analyze_position(
        self,
        ticker: str,
        position_usd: float,
        volume_series: pd.Series,
        price_series: pd.Series,
    ) -> LiquidityResult:
        """Analizza liquidità di una singola posizione.

        Parameters
        ----------
        ticker:
            Simbolo dell'asset.
        position_usd:
            Valore in USD della posizione da liquidare.
        volume_series:
            Volume giornaliero in shares (index=date).
        price_series:
            Prezzo giornaliero in USD (index=date).
        """
        # Allinea e usa gli ultimi N giorni
        common_idx = volume_series.index.intersection(price_series.index)
        vol = volume_series.reindex(common_idx).dropna()
        price = price_series.reindex(common_idx).dropna()

        common_idx2 = vol.index.intersection(price.index)
        vol = vol.reindex(common_idx2)
        price = price.reindex(common_idx2)

        # Usa ultimi lookback giorni
        if len(vol) > self._lookback:
            vol = vol.iloc[-self._lookback:]
            price = price.iloc[-self._lookback:]

        if len(vol) < 1:
            log.warning("liquidity.no_volume_data", ticker=ticker)
            return LiquidityResult(
                ticker=ticker,
                adtv_shares=0.0,
                adtv_usd=0.0,
                position_usd=position_usd,
                days_to_liquidate=float("inf"),
                liquidity_score=0.0,
                is_illiquid=True,
            )

        adtv_shares = float(np.mean(vol.to_numpy(dtype=float)))

        # ADTV in USD: volume × prezzo medio
        daily_dollar_volume = vol.to_numpy(dtype=float) * price.to_numpy(dtype=float)
        adtv_usd = float(np.mean(daily_dollar_volume))

        # Giorni per liquidare
        liquidatable_per_day = adtv_usd * self._participation_rate
        if liquidatable_per_day < 1e-6:
            days_to_liquidate = float("inf")
        else:
            days_to_liquidate = position_usd / liquidatable_per_day

        # Liquidity score [0,1]: interpolazione lineare logaritmica
        if days_to_liquidate <= MAX_LIQUIDITY_SCORE_DAYS:
            score = 1.0
        elif days_to_liquidate >= MIN_LIQUIDITY_SCORE_DAYS:
            score = 0.0
        else:
            # Interpolazione lineare nel range [MAX, MIN]
            log_d = np.log(max(days_to_liquidate, 1e-6))
            log_min = np.log(MAX_LIQUIDITY_SCORE_DAYS)
            log_max = np.log(MIN_LIQUIDITY_SCORE_DAYS)
            score = 1.0 - (log_d - log_min) / (log_max - log_min)
            score = float(np.clip(score, 0.0, 1.0))

        is_illiquid = days_to_liquidate > ILLIQUID_THRESHOLD_DAYS

        log.debug(
            "liquidity.position",
            ticker=ticker,
            adtv_usd=round(adtv_usd, 0),
            days=round(days_to_liquidate, 2),
            score=round(score, 3),
        )

        return LiquidityResult(
            ticker=ticker,
            adtv_shares=adtv_shares,
            adtv_usd=adtv_usd,
            position_usd=position_usd,
            days_to_liquidate=days_to_liquidate,
            liquidity_score=score,
            is_illiquid=is_illiquid,
        )

    def analyze_portfolio(
        self,
        positions: dict[str, float],
        volume_data: dict[str, pd.Series],
        price_data: dict[str, pd.Series],
    ) -> list[LiquidityResult]:
        """Analizza liquidità di tutto il portafoglio.

        Parameters
        ----------
        positions:
            Mappa ticker → valore USD della posizione.
        volume_data:
            Mappa ticker → serie volumi giornalieri (shares).
        price_data:
            Mappa ticker → serie prezzi giornalieri (USD).
        """
        results: list[LiquidityResult] = []
        for ticker, pos_usd in positions.items():
            if ticker not in volume_data or ticker not in price_data:
                log.warning("liquidity.missing_data", ticker=ticker)
                results.append(LiquidityResult(
                    ticker=ticker,
                    adtv_shares=0.0,
                    adtv_usd=0.0,
                    position_usd=pos_usd,
                    days_to_liquidate=float("inf"),
                    liquidity_score=0.0,
                    is_illiquid=True,
                ))
                continue

            result = self.analyze_position(
                ticker=ticker,
                position_usd=pos_usd,
                volume_series=volume_data[ticker],
                price_series=price_data[ticker],
            )
            results.append(result)

        log.info(
            "liquidity.portfolio_analyzed",
            n_positions=len(results),
            n_illiquid=sum(1 for r in results if r.is_illiquid),
        )
        return results

    def portfolio_days_90pct(self, results: list[LiquidityResult]) -> float:
        """Giorni per liquidare 90% del portafoglio (pesato per valore).

        Ordina le posizioni per liquidità (più liquide prima) e calcola
        quanti giorni servono per raggiungere il 90% del valore totale.
        """
        if not results:
            return 0.0

        total_usd = sum(r.position_usd for r in results)
        if total_usd < 1e-6:
            return 0.0

        # Ordina per days_to_liquidate crescente (più liquide prima)
        sorted_results = sorted(
            results,
            key=lambda r: r.days_to_liquidate if not np.isinf(r.days_to_liquidate) else 1e9,
        )

        target = total_usd * 0.90
        accumulated = 0.0
        max_days = 0.0

        for r in sorted_results:
            if accumulated >= target:
                break
            accumulated += r.position_usd
            if not np.isinf(r.days_to_liquidate):
                max_days = max(max_days, r.days_to_liquidate)
            else:
                max_days = float("inf")

        return max_days
