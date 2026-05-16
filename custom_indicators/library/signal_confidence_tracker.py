"""SignalConfidenceTracker — overall system signal quality score (#7, QC).

Monitors rolling IC of all core signals and produces a [0,1] score
representing how trustworthy the current signal system is.

  > 0.7 → high confidence (all signals healthy)
  0.4–0.7 → moderate (some decay)
  < 0.4 → low (many signals in decay → increase caution)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from shared.alpha_decay_monitor import AlphaDecayMonitor, IC_MIN_THRESHOLD
from shared.signal_types import SIGNAL_CUSTOM_PREFIX, Signal

__version__ = "10.0.0"

__all__ = ["SignalConfidenceTracker", "SignalQualitySnapshot"]

TRACKED_SIGNALS: list[str] = [
    "technical_composite", "macro_conviction", "labour_regime_signal",
    "sentiment_composite", "valuation_signal", "economic_surprise_index", "vix_signal",
]


@dataclass
class SignalQualitySnapshot:
    overall_score:    float
    signals_ok:       int
    signals_low_ic:   int
    signals_degraded: int
    worst_signal:     str | None
    worst_ic:         float | None


class SignalConfidenceTracker:
    """Pre-built #7 — system-wide signal quality aggregator."""

    def __init__(self, decay_monitor: AlphaDecayMonitor) -> None:
        self._monitor = decay_monitor

    def compute(self) -> SignalQualitySnapshot:
        ics: list[float] = []
        signals_ok = signals_low = signals_degraded = 0
        worst_name: str | None = None
        worst_ic:   float | None = None

        for sig_name in TRACKED_SIGNALS:
            ic, flag = self._monitor.check_decay(sig_name)
            if ic is None:
                signals_ok += 1        # benefit of the doubt
                continue
            ics.append(ic)
            if flag == "ok":
                signals_ok += 1
            elif flag == "low_ic":
                signals_low += 1
            else:
                signals_degraded += 1
            if worst_ic is None or ic < worst_ic:
                worst_ic   = ic
                worst_name = sig_name

        if not ics:
            overall = 1.0
        else:
            raw_avg = float(np.mean(ics))
            # Penalise both degraded (−10% each) and low-IC (−5% each)
            penalty = signals_degraded * 0.10 + signals_low * 0.05
            overall = float(np.clip(
                raw_avg / max(IC_MIN_THRESHOLD * 5, 0.1) - penalty, 0.0, 1.0
            ))

        return SignalQualitySnapshot(
            overall_score    = round(overall, 4),
            signals_ok       = signals_ok,
            signals_low_ic   = signals_low,
            signals_degraded = signals_degraded,
            worst_signal     = worst_name,
            worst_ic         = worst_ic,
        )

    def to_signal(self, snapshot: SignalQualitySnapshot) -> Signal:
        value = float(snapshot.overall_score * 2 - 1)   # [0,1] → [-1,1]
        return Signal(
            name          = f"{SIGNAL_CUSTOM_PREFIX}signal_confidence_tracker",
            value         = value,
            confidence    = snapshot.overall_score,
            source_module = __name__,
            metadata      = {
                "signals_ok":       snapshot.signals_ok,
                "signals_low_ic":   snapshot.signals_low_ic,
                "signals_degraded": snapshot.signals_degraded,
                "worst_signal":     snapshot.worst_signal,
                "worst_ic":         snapshot.worst_ic,
            },
        )
