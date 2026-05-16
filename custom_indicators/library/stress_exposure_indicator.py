"""StressExposureIndicator — portfolio exposure to stress scenarios (#5).

Combines historical stress scenario signals (GFC 2008, COVID 2020,
Rate Shock 2022, Custom) weighted by scenario probability.

Output: [-1, 1]
  < 0 → high stress exposure (negative signal)
  > 0 → low exposure (positive: portfolio is stress-resilient)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from shared.signal_registry import get_signal_registry
from shared.signal_types import SIGNAL_CUSTOM_PREFIX, Signal

__version__ = "10.0.0"

__all__ = ["StressExposureIndicator", "StressExposureResult"]

_DEFAULT_WEIGHTS = {
    "gfc":    0.25,
    "covid":  0.35,
    "rate":   0.25,
    "custom": 0.15,
}


@dataclass
class StressExposureResult:
    scenario_exposures: dict[str, float]    # Exposure per scenario [-1, 1]
    weighted_exposure:  float               # Weighted composite exposure
    signal_value:       float               # [-1, 1]: negative of exposure


class StressExposureIndicator:
    """Pre-built #5 — weighted stress scenario exposure.

    Reads from SignalRegistry: stress_gfc, stress_covid, stress_rate, stress_custom.
    Falls back to 0.0 (neutral) if signals not available.
    """

    def __init__(
        self,
        stress_weight_gfc:    float = _DEFAULT_WEIGHTS["gfc"],
        stress_weight_covid:  float = _DEFAULT_WEIGHTS["covid"],
        stress_weight_rate:   float = _DEFAULT_WEIGHTS["rate"],
        stress_weight_custom: float = _DEFAULT_WEIGHTS["custom"],
    ) -> None:
        total = stress_weight_gfc + stress_weight_covid + stress_weight_rate + stress_weight_custom
        self._weights = {
            "stress_gfc":    stress_weight_gfc    / total,
            "stress_covid":  stress_weight_covid  / total,
            "stress_rate":   stress_weight_rate   / total,
            "stress_custom": stress_weight_custom / total,
        }

    def compute(self) -> StressExposureResult:
        snap = get_signal_registry().snapshot()

        exposures: dict[str, float] = {
            name: float(snap.get(name, 0.0))
            for name in self._weights
        }

        weighted = float(sum(
            exposures[n] * w for n, w in self._weights.items()
        ))

        # Signal: low exposure = positive, high exposure = negative
        signal_value = float(np.clip(-weighted, -1.0, 1.0))

        return StressExposureResult(
            scenario_exposures = {k: round(v, 4) for k, v in exposures.items()},
            weighted_exposure  = round(weighted, 4),
            signal_value       = round(signal_value, 4),
        )

    def to_signal(self, result: StressExposureResult) -> Signal:
        return Signal(
            name          = f"{SIGNAL_CUSTOM_PREFIX}stress_exposure",
            value         = result.signal_value,
            confidence    = 0.65,
            source_module = __name__,
            metadata      = {
                "weighted_exposure": result.weighted_exposure,
                "scenarios": result.scenario_exposures,
            },
        )
