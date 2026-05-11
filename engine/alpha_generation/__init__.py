"""Alpha generation engine — MacroConviction + VIX Strategy.

Roadmap Unificata:
  Settimana 3: MacroConvictionCalculator (15 serie FRED)
  Settimana 4: VixSignalCalculator + StrategyComposer (HMM-aware)
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

__version__ = "2.0.0"

__all__ = [
    "ClaimsRegime",
    "CreditStressLevel",
    "CurveRegime",
    "MacroConvictionResult",
    "StrategyComposer",
    "StrategyOutput",
    "VixSignal",
    "VixSignalCalculator",
]
