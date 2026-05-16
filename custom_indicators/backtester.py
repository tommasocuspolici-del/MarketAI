"""IndicatorBacktester — walk-forward IC backtest for custom indicators.

Evaluates a custom indicator's predictive value using an expanding-window
walk-forward approach to avoid look-ahead bias.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from shared.logger import get_logger

__version__ = "10.0.0"

__all__ = [
    "BacktestResult",
    "IndicatorBacktester",
]

log = get_logger(__name__)

_MIN_TRAIN = 126    # minimum observations before first OOS evaluation


@dataclass
class BacktestResult:
    indicator_id:    str
    horizon_days:    int
    n_oos_samples:   int
    ic_oos:          float    # Out-of-sample IC (Spearman)
    hit_rate:        float    # Fraction of correct direction predictions
    oos_start_idx:   int


class IndicatorBacktester:
    """Walk-forward IC backtest.

    Usage::

        backtester = IndicatorBacktester()
        result = backtester.run(
            indicator_id    = "entry_window",
            signal_values   = historical_signal_array,
            forward_returns = aligned_returns_array,
            horizon_days    = 5,
        )
    """

    def run(
        self,
        indicator_id:    str,
        signal_values:   np.ndarray,
        forward_returns: np.ndarray,
        horizon_days:    int = 5,
        min_train:       int = _MIN_TRAIN,
    ) -> BacktestResult:
        """Walk-forward IC evaluation.

        Signals in the train window are not evaluated; OOS starts at min_train.
        Avoids look-ahead bias: at each step only past data is used to generate signals.
        """
        signal_values   = np.asarray(signal_values,   dtype=np.float64)
        forward_returns = np.asarray(forward_returns, dtype=np.float64)

        n = min(len(signal_values), len(forward_returns))
        if n < min_train + 10:
            log.warning(
                "backtester.insufficient_data",
                indicator=indicator_id,
                n=n,
                required=min_train + 10,
            )
            return BacktestResult(indicator_id, horizon_days, 0, float("nan"), float("nan"), min_train)

        oos_signals = signal_values[min_train:n]
        oos_returns = forward_returns[min_train:n]

        try:
            corr, _ = stats.spearmanr(oos_signals, oos_returns, nan_policy="omit")
            ic_oos = float(corr) if not np.isnan(corr) else float("nan")
        except Exception:
            ic_oos = float("nan")

        directions_match = np.sign(oos_signals) == np.sign(oos_returns)
        hit_rate = float(np.mean(directions_match)) if len(directions_match) > 0 else float("nan")

        log.info(
            "backtester.result",
            indicator=indicator_id,
            horizon=horizon_days,
            ic_oos=round(ic_oos, 4) if not np.isnan(ic_oos) else None,
            hit_rate=round(hit_rate, 3) if not np.isnan(hit_rate) else None,
            n_oos=len(oos_signals),
        )

        return BacktestResult(
            indicator_id  = indicator_id,
            horizon_days  = horizon_days,
            n_oos_samples = len(oos_signals),
            ic_oos        = round(ic_oos, 4) if not np.isnan(ic_oos) else float("nan"),
            hit_rate      = round(hit_rate, 3) if not np.isnan(hit_rate) else float("nan"),
            oos_start_idx = min_train,
        )
