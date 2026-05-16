"""ICWeightedEnsembleComposer — IC-weighted signal ensemble (QC upgrade).

Unlike fixed-weight ensembles, weights are proportional to the OOS IC
of each strategy in the AlphaDecayMonitor. Strategies with IC < IC_MIN
are zeroed out — they don't contribute to the composite.

Invariant: sum(weights) == 1.0 (normalised after zeroing low-IC strategies).
Rule 22: strategies beyond InvestorProfile risk tolerance → weight forced to 0.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from shared.alpha_decay_monitor import AlphaDecayMonitor, IC_MIN_THRESHOLD
from shared.logger import get_logger

__version__ = "10.0.0"

__all__ = [
    "EnsembleResult",
    "ICWeightedEnsembleComposer",
]

log = get_logger(__name__)


@dataclass
class EnsembleResult:
    ensemble_signal: float              # [-1, 1]
    weights:         dict[str, float]   # {strategy_id: weight}
    n_active:        int                # Strategies with IC ≥ threshold
    n_zeroed:        int                # Strategies zeroed (IC too low)
    fallback_used:   bool               # True if all ICs below threshold


class ICWeightedEnsembleComposer:
    """Compose strategy signals weighted by their OOS IC.

    Usage::

        composer = ICWeightedEnsembleComposer(decay_monitor=monitor)
        result   = composer.compose({
            "sma_crossover": 0.4,
            "rsi_momentum":  0.2,
            "macro_trend":  -0.1,
        })
    """

    def __init__(self, decay_monitor: AlphaDecayMonitor) -> None:
        self._monitor = decay_monitor

    def compose(
        self,
        strategy_signals: dict[str, float],
        risk_blocked:     set[str] | None = None,
    ) -> EnsembleResult:
        """Combine strategy signals with IC-proportional weights.

        Args:
            strategy_signals: {strategy_id: signal_value ∈ [-1, 1]}
            risk_blocked:     Strategy IDs to force-zero (Rule 22 risk gate).

        Returns:
            EnsembleResult with ensemble signal and weight breakdown.
        """
        if not strategy_signals:
            return EnsembleResult(0.0, {}, 0, 0, False)

        risk_blocked = risk_blocked or set()
        ids    = list(strategy_signals.keys())
        values = np.array([strategy_signals[sid] for sid in ids], dtype=np.float64)

        # IC per strategy (from AlphaDecayMonitor)
        ics = np.array([
            max(0.0, self._monitor.check_decay(f"strategy.{sid}")[0] or 0.0)
            for sid in ids
        ], dtype=np.float64)

        # Zero out: IC below threshold OR risk-blocked
        for i, sid in enumerate(ids):
            if ics[i] < IC_MIN_THRESHOLD or sid in risk_blocked:
                ics[i] = 0.0

        n_zeroed = int(np.sum(ics == 0.0))
        n_active = len(ids) - n_zeroed
        fallback = bool(ics.sum() < 1e-9)   # ensure Python bool, not np.bool_

        if fallback:
            # All strategies zeroed → equal weight (benefit of the doubt)
            weights = np.ones(len(ids), dtype=np.float64) / len(ids)
            log.warning("ensemble.all_zeroed_fallback", n_strategies=len(ids))
        else:
            weights = ics / ics.sum()

        ensemble = float(np.clip(np.dot(values, weights), -1.0, 1.0))
        weights_dict = {sid: round(float(w), 4) for sid, w in zip(ids, weights)}

        log.info(
            "ensemble.composed",
            ensemble=round(ensemble, 4),
            n_active=n_active,
            n_zeroed=n_zeroed,
            fallback=fallback,
        )
        return EnsembleResult(
            ensemble_signal = ensemble,
            weights         = weights_dict,
            n_active        = n_active,
            n_zeroed        = n_zeroed,
            fallback_used   = fallback,
        )
