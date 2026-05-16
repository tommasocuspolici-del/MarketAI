"""VolatilityAdjustedSignal — composite scaled by current VIX level (#10, QC).

Attenuates signals in high-volatility regimes to reduce false positives,
and slightly amplifies in low-vol environments (trend-following works better).

  VIX < 16  → ×1.15 (amplify — low vol, momentum favoured)
  VIX 16-25 → ×1.00 (unchanged)
  VIX 25-35 → ×0.70 (attenuate 30%)
  VIX > 35  → ×0.40 (attenuate 60% — high false positive risk)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from shared.signal_registry import get_signal_registry
from shared.signal_types import SIGNAL_CUSTOM_PREFIX, Signal

__version__ = "10.0.0"

__all__ = ["VolatilityAdjustedSignal", "VolAdjustedResult"]

_VIX_SCALE_TABLE: list[tuple[float, float, float, str]] = [
    (0.0,  16.0,  1.15, "low"),
    (16.0, 25.0,  1.00, "normal"),
    (25.0, 35.0,  0.70, "high"),
    (35.0, 999.0, 0.40, "stress"),
]


@dataclass
class VolAdjustedResult:
    raw_composite:      float
    adjusted_composite: float
    vix_level:          float
    scale_factor:       float
    vix_regime:         str


class VolatilityAdjustedSignal:
    """Pre-built #10 — volatility-scaled composite signal."""

    def compute(self) -> VolAdjustedResult:
        snap = get_signal_registry().snapshot()

        vix_signal = float(snap.get("vix_signal", 0.0))
        vix_level  = float(26.0 - vix_signal * 14.0)

        raw = float(snap.get("composite_signal_v3", 0.0))

        scale  = 1.00
        regime = "normal"
        for lo, hi, factor, label in _VIX_SCALE_TABLE:
            if lo <= vix_level < hi:
                scale  = factor
                regime = label
                break

        adjusted = float(np.clip(raw * scale, -1.0, 1.0))

        return VolAdjustedResult(
            raw_composite      = round(raw, 4),
            adjusted_composite = round(adjusted, 4),
            vix_level          = round(vix_level, 2),
            scale_factor       = scale,
            vix_regime         = regime,
        )

    def to_signal(self, result: VolAdjustedResult) -> Signal:
        # Confidence: lower when far from scale=1.0 (extreme adjustments)
        confidence = float(1.0 - abs(1.0 - result.scale_factor) / 1.0)
        return Signal(
            name          = f"{SIGNAL_CUSTOM_PREFIX}volatility_adjusted_signal",
            value         = result.adjusted_composite,
            confidence    = float(np.clip(confidence, 0.0, 1.0)),
            source_module = __name__,
            metadata      = {
                "raw_composite": result.raw_composite,
                "vix_level":     result.vix_level,
                "scale_factor":  result.scale_factor,
                "vix_regime":    result.vix_regime,
            },
        )
