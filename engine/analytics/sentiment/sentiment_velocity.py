"""SentimentVelocity — first (and second) derivative of sentiment over time.

Computes how fast sentiment is changing. A sudden shift from +0.3 to -0.2
in one day is more actionable than a steady -0.2 for weeks.

Regimes:
  'improving'     — velocity_1d > 0 consistently
  'deteriorating' — velocity_1d < 0 consistently
  'stable'        — |velocity_1d| < threshold
  'reversing'     — velocity_1d has opposite sign to velocity_5d
                    (DoD: must be detected when velocity_1d changes sign)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from engine.analytics.sentiment.schemas import SentimentVelocitySnapshot
from shared.logger import get_logger

__version__ = "10.0.0"

__all__ = ["SentimentVelocityAnalyzer"]

log = get_logger(__name__)

_STABLE_THRESHOLD = 0.05    # |velocity| below this = stable


class SentimentVelocityAnalyzer:
    """Compute sentiment velocity and regime from a time series of scores.

    Args:
        stable_threshold: |velocity_1d| below this → regime "stable".
    """

    def __init__(self, stable_threshold: float = _STABLE_THRESHOLD) -> None:
        self._stable_thr = stable_threshold

    def compute(
        self,
        scores:     list[float],    # Chronological sentiment scores (oldest → newest)
        ticker:     str | None = None,
    ) -> SentimentVelocitySnapshot:
        """Compute velocity snapshot from a time series of sentiment scores.

        Args:
            scores: At least 2 values required; 20+ for meaningful velocity_20d.
            ticker: Optional ticker/entity this series belongs to.
        """
        if len(scores) < 2:
            return SentimentVelocitySnapshot(
                ticker=ticker,
                velocity_1d=None, velocity_5d=None,
                velocity_20d=None, acceleration=None,
                regime="stable",
            )

        arr = np.array(scores, dtype=np.float64)

        v1d  = float(arr[-1] - arr[-2])                               if len(arr) >= 2  else None
        v5d  = float(arr[-1] - arr[-6])  if len(arr) >= 6  else None
        v20d = float(arr[-1] - arr[-21]) if len(arr) >= 21 else None

        # Second derivative: change in 1-day velocity
        accel = None
        if len(arr) >= 3:
            prev_v1d = float(arr[-2] - arr[-3])
            accel    = float(v1d - prev_v1d) if v1d is not None else None

        regime = self._classify_regime(v1d, v5d)

        log.debug(
            "sentiment_velocity.computed",
            ticker=ticker, v1d=round(v1d, 4) if v1d else None, regime=regime,
        )
        return SentimentVelocitySnapshot(
            ticker       = ticker,
            velocity_1d  = round(v1d,  4) if v1d  is not None else None,
            velocity_5d  = round(v5d,  4) if v5d  is not None else None,
            velocity_20d = round(v20d, 4) if v20d is not None else None,
            acceleration = round(accel, 4) if accel is not None else None,
            regime       = regime,
        )

    def _classify_regime(
        self,
        v1d: float | None,
        v5d: float | None,
    ) -> str:
        if v1d is None:
            return "stable"

        if abs(v1d) < self._stable_thr:
            return "stable"

        # Reversing: 1-day velocity has opposite sign to 5-day trend
        if v5d is not None and abs(v5d) >= self._stable_thr:
            if (v1d > 0) != (v5d > 0):
                return "reversing"

        return "improving" if v1d > 0 else "deteriorating"
