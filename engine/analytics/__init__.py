"""Engine analytics — sentiment, correlation, regime, pipeline."""
from __future__ import annotations

from engine.analytics.correlation import (
    CorrelationAnalyzer,
    CorrelationReport,
    LeadLagPair,
    MarketRegime,
    RegimeDetector,
    RegimeReport,
)
from engine.analytics.pipeline import AnalysisPipeline, PipelineReport, RiskScore
from engine.analytics.sentiment import (
    CompositeSentiment,
    SentimentAggregator,
    SentimentSignal,
    SentimentSource,
)

__version__ = "6.0.0"

__all__ = [
    "AnalysisPipeline",
    "CompositeSentiment",
    "CorrelationAnalyzer",
    "CorrelationReport",
    "LeadLagPair",
    "MarketRegime",
    "PipelineReport",
    "RegimeDetector",
    "RegimeReport",
    "RiskScore",
    "SentimentAggregator",
    "SentimentSignal",
    "SentimentSource",
]
