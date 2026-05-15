"""CompositeSignalAggregator v2 — modulo standalone (ROADMAP_ANALISI_MERCATO_v4 Blocco 2).

9 componenti pesati che aggregano tutti i segnali engine:
  vix, macro, yield_curve, credit, claims,
  labour_market, surprise, valuation, correlation

Implementazione: engine.alpha_generation.composite_signal_aggregator
Mantenuto come modulo separato per conformità alla struttura Roadmap v4.

Usage::
    from engine.alpha_generation.composite_signal_v2 import (
        CompositeSignalAggregatorV2,
        CompositeSignalOutput,
        WEIGHTS_V2,
    )
"""
from __future__ import annotations

# Re-export da composite_signal_aggregator (implementazione consolidata)
from engine.alpha_generation.composite_signal_aggregator import (
    CompositeSignalAggregator as CompositeSignalAggregatorV2,
    CompositeSignalOutput,
    _WEIGHTS as WEIGHTS_V2,
)

__version__ = "2.1.0"
__all__ = [
    "CompositeSignalAggregatorV2",
    "CompositeSignalOutput",
    "WEIGHTS_V2",
]
