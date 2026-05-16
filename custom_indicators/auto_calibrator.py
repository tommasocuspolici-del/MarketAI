"""AutoCalibrator — parameter optimisation for custom indicators (lean MVP).

Uses a simple grid search (no external dependency) over the parameter space
defined in custom_indicators.yaml. For production optimisation with Optuna,
gate behind feature_flag "custom_indicator_optuna".
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
from scipy import stats

from shared.logger import get_logger

__version__ = "10.0.0"

__all__ = [
    "CalibrationResult",
    "AutoCalibrator",
]

log = get_logger(__name__)

_MIN_IC_THRESHOLD = 0.05    # Target OOS IC for DoD criterion


@dataclass
class CalibrationResult:
    indicator_id: str
    best_params:  dict[str, Any]
    best_ic:      float
    n_trials:     int
    converged:    bool    # True if best_ic >= _MIN_IC_THRESHOLD


class AutoCalibrator:
    """Grid-search calibrator for parameterised custom indicators.

    Usage::

        calibrator = AutoCalibrator()
        result = calibrator.calibrate(
            indicator_id   = "entry_window",
            compute_fn     = lambda params: indicator_with(params).compute(),
            signal_values  = historical_signals,
            forward_returns= forward_returns,
            param_grid     = {"vix_max": [28, 30, 32], "sentiment_max": [0.6, 0.7, 0.8]},
        )
    """

    def calibrate(
        self,
        indicator_id:    str,
        compute_fn:      Callable[[dict[str, Any]], list[float]],
        signal_values:   np.ndarray,
        forward_returns: np.ndarray,
        param_grid:      dict[str, list[Any]],
    ) -> CalibrationResult:
        """Grid-search the param_grid for maximum IC.

        Args:
            indicator_id:    Indicator name (for logging).
            compute_fn:      Function that takes a params dict and returns a list
                             of signal values for the same time window as forward_returns.
            signal_values:   Baseline signal values (used as starting reference).
            forward_returns: Realised forward returns aligned with signal_values.
            param_grid:      Dict of param_name → list of candidate values.

        Returns:
            CalibrationResult with best params and IC achieved.
        """
        keys   = list(param_grid.keys())
        combos = list(itertools.product(*param_grid.values()))

        best_ic     = float("-inf")
        best_params: dict[str, Any] = {}
        n_trials = 0

        for combo in combos:
            params = dict(zip(keys, combo))
            n_trials += 1

            try:
                candidate_signals = np.array(compute_fn(params), dtype=np.float64)
                if len(candidate_signals) < 30:
                    continue
                min_len = min(len(candidate_signals), len(forward_returns))
                corr, _ = stats.spearmanr(
                    candidate_signals[:min_len], forward_returns[:min_len],
                    nan_policy="omit",
                )
                ic = float(corr) if not np.isnan(corr) else float("-inf")
            except Exception as exc:
                log.debug("auto_calibrator.trial_failed", params=params, error=str(exc))
                ic = float("-inf")

            if ic > best_ic:
                best_ic     = ic
                best_params = params

        log.info(
            "auto_calibrator.done",
            indicator=indicator_id,
            best_ic=round(best_ic, 4),
            n_trials=n_trials,
            converged=best_ic >= _MIN_IC_THRESHOLD,
        )

        return CalibrationResult(
            indicator_id = indicator_id,
            best_params  = best_params,
            best_ic      = round(best_ic, 4),
            n_trials     = n_trials,
            converged    = best_ic >= _MIN_IC_THRESHOLD,
        )
