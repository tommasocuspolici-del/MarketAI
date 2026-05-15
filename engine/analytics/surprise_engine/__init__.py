"""engine.analytics.surprise_engine — Economic Surprise Engine (Blocco C).

ROADMAP_ANALISI_MERCATO_v4 — Blocco 2.
Struttura moduli:
  · surprise_calculator.py        — SurpriseCalculator (z-score)
  · sector_surprise_aggregator.py — SectorSurpriseAggregator (EMA settoriale)
  · surprise_signal_generator.py  — SurpriseSignalGenerator (segnale [-1,1])
  · surprise_aggregator_v2.py     — Pipeline orchestrator + accuracy tracking
  · consensus_loader.py           — ConsensusLoader (YAML + FRED-derived)
  · surprise_momentum.py          — SurpriseMomentum (accelerazione)
  · schemas.py                    — Pandera schemas
"""
from __future__ import annotations

from engine.analytics.surprise_engine.surprise_engine import (
    SurpriseCalculator,
    SectorSurpriseAggregator,
    SurpriseSignalGenerator,
    IndicatorSurprise,
    SectorSurpriseIndex,
    SurpriseCompositeSignal,
)
from engine.analytics.surprise_engine.surprise_momentum import (
    SurpriseMomentum,
    MomentumSignal,
)
from engine.analytics.surprise_engine.consensus_loader import ConsensusLoader
from engine.analytics.surprise_engine.surprise_aggregator_v2 import (
    SurpriseAggregatorV2,
    SurpriseAccuracyTracker,
    AutoWeightCalibrator,
    PipelineResult,
)

__version__ = "9.0.0"

__all__ = [
    "SurpriseCalculator",
    "SectorSurpriseAggregator",
    "SurpriseSignalGenerator",
    "IndicatorSurprise",
    "SectorSurpriseIndex",
    "SurpriseCompositeSignal",
    "SurpriseMomentum",
    "MomentumSignal",
    "ConsensusLoader",
    "SurpriseAggregatorV2",
    "SurpriseAccuracyTracker",
    "AutoWeightCalibrator",
    "PipelineResult",
]
