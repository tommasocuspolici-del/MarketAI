"""CustomIndicatorICTracker — IC computation for custom indicators (QC-2).

Calculates Spearman IC between a custom indicator's historical values and
forward returns, then updates AlphaDecayMonitor for automatic weight decay.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy import stats

from shared.alpha_decay_monitor import AlphaDecayMonitor, IC_MIN_THRESHOLD
from shared.logger import get_logger

__version__ = "10.0.0"

__all__ = ["CustomIndicatorICTracker"]

log = get_logger(__name__)

_MIN_OBSERVATIONS = 30
_HORIZON_DAYS: list[int] = [5, 21]


class CustomIndicatorICTracker:
    """Compute IC and update AlphaDecayMonitor for each custom indicator.

    Usage::

        tracker = CustomIndicatorICTracker(decay_monitor=monitor)
        ic = tracker.compute_ic(signal_values, forward_returns, "entry_window")
    """

    def __init__(self, decay_monitor: AlphaDecayMonitor) -> None:
        self._monitor = decay_monitor

    def compute_ic(
        self,
        signal_values:   np.ndarray[Any, Any],
        forward_returns: np.ndarray[Any, Any],
        indicator_id:    str,
    ) -> float:
        """Compute Spearman IC between signal and forward returns.

        Args:
            signal_values:   Historical signal values (already lag-adjusted).
            forward_returns: Aligned forward returns for the same time window.
            indicator_id:    Indicator name (for logging and monitor update).

        Returns:
            IC ∈ [-1, 1], or float('nan') if insufficient data.
        """
        if len(signal_values) < _MIN_OBSERVATIONS:
            log.warning(
                "ic_tracker.insufficient_data",
                indicator=indicator_id,
                n=len(signal_values),
                required=_MIN_OBSERVATIONS,
            )
            return float("nan")

        if len(signal_values) != len(forward_returns):
            raise ValueError(
                f"signal_values and forward_returns must have same length: "
                f"{len(signal_values)} vs {len(forward_returns)}"
            )

        try:
            corr, p_value = stats.spearmanr(signal_values, forward_returns, nan_policy="omit")
            ic = float(corr) if not np.isnan(corr) else 0.0
        except Exception as exc:
            log.error("ic_tracker.computation_failed", indicator=indicator_id, error=str(exc))
            return float("nan")

        log.info(
            "ic_tracker.computed",
            indicator=indicator_id,
            ic=round(ic, 4),
            p_value=round(float(p_value), 4),
            n=len(signal_values),
        )

        # Feed into AlphaDecayMonitor: use latest pair as representative update
        if len(signal_values) > 0 and len(forward_returns) > 0:
            self._monitor.update(
                signal_name    = f"custom.{indicator_id}",
                signal_value   = float(signal_values[-1]),
                forward_return = float(forward_returns[-1]),
            )

        if not np.isnan(ic) and ic < IC_MIN_THRESHOLD:
            log.warning(
                "ic_tracker.low_ic_detected",
                indicator=indicator_id,
                ic=round(ic, 4),
                threshold=IC_MIN_THRESHOLD,
                action="weight_reduced_in_composite",
            )

        return ic

    def batch_update(
        self,
        signal_values:   np.ndarray[Any, Any],
        forward_returns: np.ndarray[Any, Any],
        indicator_id:    str,
        horizon_days:    int = 5,
    ) -> None:
        """Feed all historical (signal, return) pairs into AlphaDecayMonitor."""
        for sv, fr in zip(signal_values, forward_returns):
            if not (np.isnan(sv) or np.isnan(fr)):
                self._monitor.update(
                    signal_name    = f"custom.{indicator_id}",
                    signal_value   = float(sv),
                    forward_return = float(fr),
                    horizon_days   = horizon_days,
                )
