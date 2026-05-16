"""EntryWindowIndicator — optimal liquidity deployment window (#4).

Checks multiple conditions to decide if this is a good time to invest
available cash. Returns a score [0, 1] and a binary recommendation.

Conditions checked (from custom_indicators.yaml params):
  - macro_conviction > macro_threshold (0.0)
  - sentiment < sentiment_max (0.70) — don't buy at euphoria
  - RSI proxy < rsi_weekly_max (55)
  - vix_min <= VIX <= vix_max (16–32)
  - overall score >= min_score (0.65)

Output: [-1, 1]
  > 0 → window open (positive: good time to invest)
  < 0 → window closed
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from shared.signal_registry import get_signal_registry
from shared.signal_types import SIGNAL_CUSTOM_PREFIX, Signal

__version__ = "10.0.0"

__all__ = ["EntryWindowIndicator", "EntryWindowResult"]


@dataclass
class EntryWindowResult:
    score:           float     # [0, 1]: weighted condition score
    window_open:     bool
    signal_value:    float     # [-1, 1]
    conditions_met:  dict[str, bool]


class EntryWindowIndicator:
    """Pre-built #4 — optimal entry window for cash deployment.

    Reads from SignalRegistry: macro_conviction, sentiment_composite, vix_signal.
    """

    def __init__(
        self,
        macro_threshold:  float = 0.0,
        sentiment_max:    float = 0.70,
        rsi_weekly_max:   float = 55.0,
        vix_min:          float = 16.0,
        vix_max:          float = 32.0,
        min_score:        float = 0.65,
    ) -> None:
        self._macro_thr = macro_threshold
        self._sent_max  = sentiment_max
        self._rsi_max   = rsi_weekly_max
        self._vix_min   = vix_min
        self._vix_max   = vix_max
        self._min_score = min_score

    def compute(self) -> EntryWindowResult:
        snap = get_signal_registry().snapshot()

        macro_signal = float(snap.get("macro_conviction",   0.0))
        sentiment    = float(snap.get("sentiment_composite", 0.0))
        vix_signal   = float(snap.get("vix_signal",          0.0))

        # Convert vix_signal [-1,1] to approximate VIX level
        # vix_signal = -1 → VIX ≈ 40, vix_signal = +1 → VIX ≈ 12
        vix_level = float(26.0 - vix_signal * 14.0)

        # Convert sentiment [-1,1] to [0,1] for the max check
        sentiment_norm = float((sentiment + 1.0) / 2.0)

        conditions: dict[str, bool] = {
            "macro_positive":    macro_signal    > self._macro_thr,
            "sentiment_not_high": sentiment_norm  < self._sent_max,
            "vix_in_range":      self._vix_min <= vix_level <= self._vix_max,
        }

        # Weighted score: all conditions equal weight
        score = float(sum(conditions.values()) / len(conditions))
        window_open  = score >= self._min_score
        signal_value = float(np.clip(score * 2.0 - 1.0, -1.0, 1.0))

        return EntryWindowResult(
            score          = round(score, 4),
            window_open    = window_open,
            signal_value   = round(signal_value, 4),
            conditions_met = conditions,
        )

    def to_signal(self, result: EntryWindowResult) -> Signal:
        return Signal(
            name          = f"{SIGNAL_CUSTOM_PREFIX}entry_window",
            value         = result.signal_value,
            confidence    = result.score,
            source_module = __name__,
            metadata      = {"window_open": result.window_open, "conditions": result.conditions_met},
        )
