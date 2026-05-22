"""Walk-Forward Optimization Runner."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable

import numpy as np
import pandas as pd

from engine.alpha_generation.backtest_engine.psr_calculator import (
    PSRResult,
    probabilistic_sharpe_ratio,
)
from shared.logger import get_logger

log = get_logger(__name__)

IN_SAMPLE_YEARS: int = 3
OOS_YEARS: int = 1
STEP_MONTHS: int = 3
MIN_OOS_PERIODS: int = 60


@dataclass
class WFOConfig:
    in_sample_years: int = IN_SAMPLE_YEARS
    oos_years: int = OOS_YEARS
    step_months: int = STEP_MONTHS
    min_oos_periods: int = MIN_OOS_PERIODS


@dataclass
class WFOFold:
    fold_n: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    oos_returns: np.ndarray
    oos_metrics: dict[str, float]   # mse, mae, sharpe, directional_acc
    psr_result: PSRResult


@dataclass
class WFOResult:
    folds: list[WFOFold]
    combined_oos_returns: np.ndarray
    combined_psr: PSRResult
    avg_directional_acc: float
    avg_sharpe: float
    is_robust: bool   # True if all folds PSR > 0.90


class WFORunner:
    """Esegue Walk-Forward Optimization su una funzione di strategia."""

    def __init__(self, config: WFOConfig | None = None) -> None:
        self._config = config or WFOConfig()

    # ------------------------------------------------------------------ #
    # Main entry point                                                     #
    # ------------------------------------------------------------------ #

    def run(
        self,
        prices: pd.Series,
        strategy_fn: Callable[[pd.Series], pd.Series],
        signal_to_returns: Callable[[pd.Series, pd.Series], np.ndarray] | None = None,
    ) -> WFOResult:
        """Esegue WFO e aggrega i risultati.

        Args:
            prices:            Serie prezzi storici con DatetimeIndex.
            strategy_fn:       Funzione (train_prices) → signals (pd.Series).
                               I signals sono applicati al periodo OOS.
            signal_to_returns: (opzionale) Funzione (signals, oos_prices) → returns.
                               Default: rendimenti posizionali (long/short = +1/-1).

        Returns:
            WFOResult aggregato su tutti i fold.
        """
        if not isinstance(prices.index, pd.DatetimeIndex):
            raise ValueError("prices must have a DatetimeIndex")

        folds_slices = self._split_folds(prices.index)

        if not folds_slices:
            log.warning("wfo.no_folds_generated", n_prices=len(prices))
            empty_psr = probabilistic_sharpe_ratio(np.array([0.0]))
            return WFOResult(
                folds=[],
                combined_oos_returns=np.array([]),
                combined_psr=empty_psr,
                avg_directional_acc=0.0,
                avg_sharpe=0.0,
                is_robust=False,
            )

        all_oos_returns: list[np.ndarray] = []
        wfo_folds: list[WFOFold] = []

        for fold_n, (train_slice, test_slice) in enumerate(folds_slices):
            train_prices = prices.iloc[train_slice]
            test_prices = prices.iloc[test_slice]

            if len(test_prices) < self._config.min_oos_periods:
                log.debug("wfo.fold_too_short", fold_n=fold_n, n=len(test_prices))
                continue

            try:
                # Addestra strategia sul train set
                signals = strategy_fn(train_prices)
                # Genera segnali sull'OOS (applica la stessa logica)
                oos_signals = strategy_fn(test_prices)

                # Converte segnali in rendimenti
                if signal_to_returns is not None:
                    oos_returns = signal_to_returns(oos_signals, test_prices)
                else:
                    oos_returns = self._default_signal_to_returns(oos_signals, test_prices)

                fold = self._evaluate_fold(
                    returns=oos_returns,
                    fold_n=fold_n,
                    dates=(
                        train_prices.index[0].date(),
                        train_prices.index[-1].date(),
                        test_prices.index[0].date(),
                        test_prices.index[-1].date(),
                    ),
                )
                wfo_folds.append(fold)
                all_oos_returns.append(oos_returns)

            except Exception as exc:
                log.error("wfo.fold_failed", fold_n=fold_n, error=str(exc))

        if not wfo_folds:
            log.warning("wfo.all_folds_failed")
            empty_psr = probabilistic_sharpe_ratio(np.array([0.0]))
            return WFOResult(
                folds=[],
                combined_oos_returns=np.array([]),
                combined_psr=empty_psr,
                avg_directional_acc=0.0,
                avg_sharpe=0.0,
                is_robust=False,
            )

        combined_returns = np.concatenate(all_oos_returns)
        combined_psr = probabilistic_sharpe_ratio(combined_returns)

        avg_dir_acc = float(np.mean([f.oos_metrics["directional_acc"] for f in wfo_folds]))
        avg_sharpe = float(np.mean([f.oos_metrics["sharpe"] for f in wfo_folds]))
        is_robust = all(f.psr_result.psr > 0.90 for f in wfo_folds)

        log.info(
            "wfo.completed",
            n_folds=len(wfo_folds),
            avg_sharpe=round(avg_sharpe, 4),
            avg_directional_acc=round(avg_dir_acc, 4),
            is_robust=is_robust,
        )

        return WFOResult(
            folds=wfo_folds,
            combined_oos_returns=combined_returns,
            combined_psr=combined_psr,
            avg_directional_acc=avg_dir_acc,
            avg_sharpe=avg_sharpe,
            is_robust=is_robust,
        )

    # ------------------------------------------------------------------ #
    # Fold splitting                                                       #
    # ------------------------------------------------------------------ #

    def _split_folds(self, index: pd.DatetimeIndex) -> list[tuple[slice, slice]]:
        """Genera coppie (train_slice, test_slice) con finestre scivolanti."""
        cfg = self._config
        in_sample_days = cfg.in_sample_years * 252
        oos_days = cfg.oos_years * 252
        step_days = cfg.step_months * 21  # ~21 trading days per mese

        n = len(index)
        folds: list[tuple[slice, slice]] = []

        train_start = 0
        while True:
            train_end = train_start + in_sample_days
            test_start = train_end
            test_end = test_start + oos_days

            if test_end > n:
                break

            folds.append((
                slice(train_start, train_end),
                slice(test_start, test_end),
            ))
            train_start += step_days

        log.debug("wfo.folds_split", n_folds=len(folds), n_total=n)
        return folds

    # ------------------------------------------------------------------ #
    # Fold evaluation                                                      #
    # ------------------------------------------------------------------ #

    def _evaluate_fold(
        self,
        returns: np.ndarray,
        fold_n: int,
        dates: tuple[date, date, date, date],
    ) -> WFOFold:
        """Calcola metriche OOS e PSR per un singolo fold."""
        psr_result = probabilistic_sharpe_ratio(returns)

        # Metriche base
        n = len(returns)
        mse = float(np.mean(returns ** 2)) if n > 0 else 0.0
        mae = float(np.mean(np.abs(returns))) if n > 0 else 0.0

        # Sharpe periodico
        mu = float(np.mean(returns))
        sigma = float(np.std(returns, ddof=1)) if n > 1 else 1.0
        sharpe = mu / sigma if sigma > 0.0 else 0.0

        # Directional accuracy: P(rendimento positivo)
        directional_acc = float(np.mean(returns > 0.0)) if n > 0 else 0.0

        train_start, train_end, test_start, test_end = dates

        log.debug(
            "wfo.fold_evaluated",
            fold_n=fold_n,
            n=n,
            sharpe=round(sharpe, 4),
            psr=round(psr_result.psr, 4),
        )

        return WFOFold(
            fold_n=fold_n,
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            oos_returns=returns,
            oos_metrics={
                "mse": mse,
                "mae": mae,
                "sharpe": sharpe,
                "directional_acc": directional_acc,
            },
            psr_result=psr_result,
        )

    # ------------------------------------------------------------------ #
    # Default signal to returns converter                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _default_signal_to_returns(
        signals: pd.Series,
        prices: pd.Series,
    ) -> np.ndarray:
        """Converte segnali {+1, 0, -1} in rendimenti posizionali.

        Rendimento = signal * (pct_change del prezzo al passo successivo).
        """
        pct_returns = prices.pct_change().fillna(0.0)
        # Allinea per indice
        common_idx = signals.index.intersection(pct_returns.index)
        if common_idx.empty:
            # Fallback: usa i rendimenti del periodo OOS direttamente
            return pct_returns.values.astype(float)
        pos_returns = (signals.loc[common_idx] * pct_returns.loc[common_idx]).values
        return pos_returns.astype(float)
