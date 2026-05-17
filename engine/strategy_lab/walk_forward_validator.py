"""WalkForwardValidator — purged walk-forward validation (QC, Rule 23 extended).

No strategy may be marked is_active=True in the StrategyRegistry without first
passing walk-forward validation. This enforces out-of-sample discipline and
prevents in-sample overfitting.

Purge buffer: 1 month gap between train and test windows eliminates leakage
from slowly-propagating signals (earnings, macro revisions).

Uses vectorbt for portfolio simulation when available; falls back to a
numpy-based Sharpe estimator when vectorbt raises.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from shared.logger import get_logger

__version__ = "10.0.0"

__all__ = [
    "WalkForwardResult",
    "WalkForwardValidator",
]

log = get_logger(__name__)

_PURGE_MONTHS = 1
_RISK_FREE     = 0.04   # annualised risk-free rate for Sharpe (4%)


@dataclass
class WalkForwardResult:
    n_folds:         int
    sharpe_oos_mean: float
    sharpe_oos_std:  float
    sharpe_oos_min:  float
    is_validated:    bool
    validation_note: str
    fold_sharpes:    list[float] = field(default_factory=list)


class WalkForwardValidator:
    """Purged walk-forward validator for strategies.

    Args:
        train_months:   Training window in months (default 24).
        test_months:    Test window in months (default 6).
        min_sharpe_oos: Minimum mean OOS Sharpe for validation (default 0.30).
    """

    PURGE_BUFFER_MONTHS: int = _PURGE_MONTHS

    def __init__(
        self,
        train_months:   int   = 24,
        test_months:    int   = 6,
        min_sharpe_oos: float = 0.30,
    ) -> None:
        self.train_months   = train_months
        self.test_months    = test_months
        self.min_sharpe_oos = min_sharpe_oos

    def validate(
        self,
        ohlcv:       pd.DataFrame,
        strategy_fn: Callable[[pd.DataFrame], tuple[pd.Series, pd.Series]],
    ) -> WalkForwardResult:
        """Run purged walk-forward validation.

        Args:
            ohlcv:       OHLCV DataFrame with DatetimeIndex. Must have a 'close' column.
            strategy_fn: fn(train_df) → (entries: pd.Series[bool], exits: pd.Series[bool])
                         Both series must be indexed like train_df.

        Returns:
            WalkForwardResult with OOS Sharpe statistics.
        """
        step  = pd.DateOffset(months=self.test_months)
        purge = pd.DateOffset(months=self.PURGE_BUFFER_MONTHS)

        sharpes: list[float] = []
        start = ohlcv.index[0]
        end   = ohlcv.index[-1]

        while True:
            train_end  = start + pd.DateOffset(months=self.train_months)
            test_start = train_end + purge
            test_end   = test_start + pd.DateOffset(months=self.test_months)

            if test_end > end:
                break

            train_df = ohlcv.loc[start:train_end]
            test_df  = ohlcv.loc[test_start:test_end]

            if len(train_df) < 60 or len(test_df) < 20:
                start += step
                continue

            try:
                entries, exits = strategy_fn(train_df)
                sharpe = self._evaluate_oos(test_df, entries, exits)
                sharpes.append(sharpe)
                log.debug(
                    "walk_forward.fold",
                    train_end=str(train_end.date()),
                    test_end=str(test_end.date()),
                    sharpe=round(sharpe, 3),
                )
            except Exception as exc:
                log.warning("walk_forward.fold_failed", error=str(exc))

            start += step

        return self._build_result(sharpes)

    # ── Internal ───────────────────────────────────────────────────────────

    def _evaluate_oos(
        self,
        test_df:  pd.DataFrame,
        entries:  pd.Series,
        exits:    pd.Series,
    ) -> float:
        """Evaluate OOS Sharpe using vectorbt (primary) or numpy (fallback)."""
        try:
            import vectorbt as vbt  # type: ignore[import-untyped]
            entries_test = (
                entries.reindex(test_df.index).fillna(False).shift(1).fillna(False)
            )
            exits_test = (
                exits.reindex(test_df.index).fillna(False).shift(1).fillna(False)
            )
            pf    = vbt.Portfolio.from_signals(
                test_df["close"], entries_test, exits_test,
                fees=0.001, slippage=0.001, freq="1D",
            )
            stats = pf.stats()
            raw = float(stats.get("Sharpe Ratio", 0.0) or 0.0)
            return float(np.clip(raw, -50.0, 50.0)) if np.isfinite(raw) else 0.0
        except Exception:
            return self._numpy_sharpe(test_df, entries, exits)

    @staticmethod
    def _numpy_sharpe(
        test_df:  pd.DataFrame,
        entries:  pd.Series,
        exits:    pd.Series,
    ) -> float:
        """Numpy-based Sharpe estimator when vectorbt unavailable."""
        close  = test_df["close"].values.astype(np.float64)
        rets   = np.diff(close) / close[:-1]

        # Build a simple position series from entries/exits
        entries_arr = entries.reindex(test_df.index).fillna(False).values[:-1]
        exits_arr   = exits.reindex(test_df.index).fillna(False).values[:-1]

        position  = np.zeros(len(rets), dtype=np.float64)
        in_trade  = False
        for i in range(len(rets)):
            if entries_arr[i] and not in_trade:
                in_trade = True
            if exits_arr[i] and in_trade:
                in_trade = False
            position[i] = 1.0 if in_trade else 0.0

        strat_rets = rets * position
        if strat_rets.std() < 1e-9:
            return 0.0
        daily_rf   = _RISK_FREE / 252
        excess     = strat_rets - daily_rf
        return float(np.sqrt(252) * excess.mean() / excess.std())

    def _build_result(self, sharpes: list[float]) -> WalkForwardResult:
        if not sharpes:
            return WalkForwardResult(
                n_folds=0, sharpe_oos_mean=0.0, sharpe_oos_std=0.0,
                sharpe_oos_min=0.0, is_validated=False,
                validation_note="Insufficient data for walk-forward validation",
                fold_sharpes=[],
            )

        mean_s = float(np.mean(sharpes))
        ok     = mean_s >= self.min_sharpe_oos

        log.info(
            "walk_forward.complete",
            n_folds=len(sharpes),
            sharpe_mean=round(mean_s, 3),
            validated=ok,
        )
        return WalkForwardResult(
            n_folds         = len(sharpes),
            sharpe_oos_mean = round(mean_s, 4),
            sharpe_oos_std  = round(float(np.std(sharpes)), 4),
            sharpe_oos_min  = round(float(np.min(sharpes)), 4),
            is_validated    = ok,
            validation_note = (
                f"Validated: OOS Sharpe {mean_s:.3f} ≥ {self.min_sharpe_oos}"
                if ok else
                f"Not validated: OOS Sharpe {mean_s:.3f} < {self.min_sharpe_oos}"
            ),
            fold_sharpes    = [round(s, 4) for s in sharpes],
        )
