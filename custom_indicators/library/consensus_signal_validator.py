"""ConsensusSignalValidator — signal only when N sources agree (#9, QC).

Emits a directional signal only if ≥ min_agreeing signals are aligned.
Output = 0.0 means "no consensus" — not neutral, just "wait".

Output: [-1, 1]
  bullish  (≥ 3 signals > direction_threshold)
  bearish  (≥ 3 signals < -direction_threshold)
  0.0      (no consensus — neither bullish nor bearish)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from shared.signal_registry import get_signal_registry
from shared.signal_types import SIGNAL_CUSTOM_PREFIX, Signal

__version__ = "10.0.0"

__all__ = ["ConsensusSignalValidator", "ConsensusResult"]

_TRACKED_SIGNALS: list[str] = [
    "technical_composite", "macro_conviction", "labour_regime_signal",
    "sentiment_composite", "valuation_signal", "economic_surprise_index", "vix_signal",
]


@dataclass
class ConsensusResult:
    consensus_value:   float
    n_bullish:         int
    n_bearish:         int
    n_neutral:         int
    consensus_reached: bool
    direction:         str                # 'bullish' | 'bearish' | 'no_consensus'
    agreeing_signals:  list[str] = field(default_factory=list)


class ConsensusSignalValidator:
    """Pre-built #9 — multi-source consensus gate."""

    def __init__(
        self,
        min_agreeing:        int   = 3,
        direction_threshold: float = 0.15,
    ) -> None:
        self.min_agreeing        = min_agreeing
        self.direction_threshold = direction_threshold

    def compute(self) -> ConsensusResult:
        snap = get_signal_registry().snapshot()

        bullish: list[tuple[str, float]] = []
        bearish: list[tuple[str, float]] = []
        neutral_count = 0

        for sig_name in _TRACKED_SIGNALS:
            value = snap.get(sig_name)
            if value is None:
                continue
            if value > self.direction_threshold:
                bullish.append((sig_name, value))
            elif value < -self.direction_threshold:
                bearish.append((sig_name, value))
            else:
                neutral_count += 1

        if len(bullish) >= self.min_agreeing:
            values          = np.array([v for _, v in bullish], dtype=np.float64)
            consensus_value = float(np.mean(values))
            direction       = "bullish"
            reached         = True
            agreeing        = [n for n, _ in bullish]
        elif len(bearish) >= self.min_agreeing:
            values          = np.array([v for _, v in bearish], dtype=np.float64)
            consensus_value = float(np.mean(values))
            direction       = "bearish"
            reached         = True
            agreeing        = [n for n, _ in bearish]
        else:
            consensus_value = 0.0
            direction       = "no_consensus"
            reached         = False
            agreeing        = []

        return ConsensusResult(
            consensus_value   = float(np.clip(consensus_value, -1.0, 1.0)),
            n_bullish         = len(bullish),
            n_bearish         = len(bearish),
            n_neutral         = neutral_count,
            consensus_reached = reached,
            direction         = direction,
            agreeing_signals  = agreeing,
        )

    def to_signal(self, result: ConsensusResult) -> Signal:
        n_total = len(_TRACKED_SIGNALS)
        confidence = float((result.n_bullish + result.n_bearish) / max(n_total, 1))
        return Signal(
            name          = f"{SIGNAL_CUSTOM_PREFIX}consensus_signal_validator",
            value         = result.consensus_value,
            confidence    = confidence,
            source_module = __name__,
            metadata      = {
                "n_bullish": result.n_bullish,
                "n_bearish": result.n_bearish,
                "direction": result.direction,
                "reached":   result.consensus_reached,
                "agreeing":  result.agreeing_signals,
            },
        )
