"""RegimeSignalFilter — IC-weighted composite excluding low-IC signals (#8, QC).

Builds a composite using only signals whose IC exceeds a per-regime threshold,
weighting remaining signals by their actual IC value.

Output: [-1, 1] — filtered composite (0.0 if all signals filtered out)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from shared.alpha_decay_monitor import AlphaDecayMonitor
from shared.signal_registry import get_signal_registry
from shared.signal_types import SIGNAL_CUSTOM_PREFIX, Signal

__version__ = "10.0.0"

__all__ = ["RegimeSignalFilter", "RegimeFilteredSignal"]

_IC_REGIME_THRESHOLD = 0.03

_CORE_SIGNALS: list[str] = [
    "technical_composite", "macro_conviction", "labour_regime_signal",
    "sentiment_composite", "valuation_signal", "economic_surprise_index",
]


@dataclass
class RegimeFilteredSignal:
    filtered_composite:  float
    n_signals_used:      int
    n_signals_filtered:  int
    signal_details:      dict[str, float]


class RegimeSignalFilter:
    """Pre-built #8 — regime-conditioned IC-weighted composite."""

    def __init__(
        self,
        decay_monitor:     AlphaDecayMonitor,
        ic_regime_threshold: float = _IC_REGIME_THRESHOLD,
    ) -> None:
        self._monitor   = decay_monitor
        self._threshold = ic_regime_threshold

    def compute(self, current_regime: str = "transition") -> RegimeFilteredSignal:
        snap = get_signal_registry().snapshot()

        used:     list[tuple[str, float, float]] = []    # (name, value, ic)
        filtered: list[str] = []

        for sig_name in _CORE_SIGNALS:
            value = snap.get(sig_name)
            if value is None:
                continue
            ic, _ = self._monitor.check_decay(sig_name)
            ic_val = ic if ic is not None else 0.05   # benefit of the doubt

            if ic_val >= self._threshold:
                used.append((sig_name, value, ic_val))
            else:
                filtered.append(sig_name)

        if not used:
            return RegimeFilteredSignal(0.0, 0, len(filtered), {})

        ics     = np.array([ic for _, _, ic in used], dtype=np.float64)
        values  = np.array([v  for _, v,  _ in used], dtype=np.float64)
        weights = ics / ics.sum()
        composite = float(np.clip(np.dot(values, weights), -1.0, 1.0))

        return RegimeFilteredSignal(
            filtered_composite = round(composite, 4),
            n_signals_used     = len(used),
            n_signals_filtered = len(filtered),
            signal_details     = {n: round(ic, 4) for n, _, ic in used},
        )

    def to_signal(self, result: RegimeFilteredSignal) -> Signal:
        n_total = result.n_signals_used + result.n_signals_filtered
        return Signal(
            name          = f"{SIGNAL_CUSTOM_PREFIX}regime_signal_filter",
            value         = result.filtered_composite,
            confidence    = float(result.n_signals_used / max(n_total, 1)),
            source_module = __name__,
            metadata      = {
                "n_used":     result.n_signals_used,
                "n_filtered": result.n_signals_filtered,
                "details":    result.signal_details,
            },
        )
