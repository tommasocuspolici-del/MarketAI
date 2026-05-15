"""Alpha generation engine — Composite Signal v2/v3 + VIX + Macro.

Moduli principali:
  · composite_signal_aggregator.py  — CompositeSignalAggregator v2.1 (9 componenti)
  · composite_signal_v2.py          — Alias v2 per roadmap compliance
  · macro_conviction.py             — MacroConvictionCalculator (15 serie FRED)
  · vix_signal_calculator.py        — VixSignalCalculator + StrategyComposer
"""
from __future__ import annotations

from engine.alpha_generation.schemas import (
    ClaimsRegime,
    CreditStressLevel,
    CurveRegime,
    MacroConvictionResult,
)
from engine.alpha_generation.strategy_composer import StrategyComposer, StrategyOutput
from engine.alpha_generation.vix_signal_calculator import VixSignal, VixSignalCalculator
from engine.alpha_generation.composite_signal_aggregator import (
    CompositeSignalAggregator,
    CompositeSignalOutput,
)
from engine.alpha_generation.composite_signal_v2 import (
    CompositeSignalAggregatorV2,
    WEIGHTS_V2,
)

__version__ = "3.1.0"

__all__ = [
    "ClaimsRegime",
    "CreditStressLevel",
    "CurveRegime",
    "MacroConvictionResult",
    "StrategyComposer",
    "StrategyOutput",
    "VixSignal",
    "VixSignalCalculator",
    "CompositeSignalAggregator",
    "CompositeSignalOutput",
    "CompositeSignalAggregatorV2",
    "WEIGHTS_V2",
]
