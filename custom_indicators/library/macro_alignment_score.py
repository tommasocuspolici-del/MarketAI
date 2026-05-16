"""MacroAlignmentScore — macro signal alignment with portfolio (#3).

Reads macro_conviction, real_yield and credit spread signals from the
SignalRegistry and produces an alignment score: how well the current
macro environment suits a long-equity / growth portfolio.

Output: [-1, 1]
  > 0 → macro environment favourable for portfolio
  < 0 → macro environment adverse
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from shared.signal_registry import get_signal_registry
from shared.signal_types import SIGNAL_CUSTOM_PREFIX, Signal

__version__ = "10.0.0"

__all__ = ["MacroAlignmentScore", "MacroAlignmentResult"]

_MACRO_WEIGHT_DEFAULT  = 0.50
_YIELD_WEIGHT_DEFAULT  = 0.30
_CREDIT_WEIGHT_DEFAULT = 0.20


@dataclass
class MacroAlignmentResult:
    macro_score:    float
    yield_score:    float
    credit_score:   float
    composite:      float
    signal_value:   float


class MacroAlignmentScore:
    """Pre-built #3 — macro alignment with long-equity portfolio.

    Reads from SignalRegistry:
        macro_conviction       → macro tailwinds/headwinds
        real_yield_signal      → real yield (negative = good for equity)
        credit_spread_signal   → credit spread (negative = tightening = good)
    """

    def __init__(
        self,
        macro_weight:  float = _MACRO_WEIGHT_DEFAULT,
        yield_weight:  float = _YIELD_WEIGHT_DEFAULT,
        credit_weight: float = _CREDIT_WEIGHT_DEFAULT,
    ) -> None:
        total = macro_weight + yield_weight + credit_weight
        self._w_macro  = macro_weight  / total
        self._w_yield  = yield_weight  / total
        self._w_credit = credit_weight / total

    def compute(self) -> MacroAlignmentResult:
        snap = get_signal_registry().snapshot()

        macro_score  = float(snap.get("macro_conviction",     0.0))
        yield_score  = float(snap.get("real_yield_signal",    0.0))
        credit_score = float(snap.get("credit_spread_signal", 0.0))

        composite = (
            self._w_macro  * macro_score +
            self._w_yield  * yield_score +
            self._w_credit * credit_score
        )
        signal_value = float(np.clip(composite, -1.0, 1.0))

        return MacroAlignmentResult(
            macro_score  = round(macro_score, 4),
            yield_score  = round(yield_score, 4),
            credit_score = round(credit_score, 4),
            composite    = round(composite, 4),
            signal_value = round(signal_value, 4),
        )

    def to_signal(self, result: MacroAlignmentResult) -> Signal:
        return Signal(
            name          = f"{SIGNAL_CUSTOM_PREFIX}macro_alignment_score",
            value         = result.signal_value,
            confidence    = 0.75,
            source_module = __name__,
            metadata      = {
                "macro":  result.macro_score,
                "yield":  result.yield_score,
                "credit": result.credit_score,
            },
        )
