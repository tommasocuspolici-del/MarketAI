"""Correlation analytics — rolling, dynamic, lead-lag + regime detection."""
from __future__ import annotations

from engine.analytics.correlation.analyzer import (
    CorrelationAnalyzer,
    CorrelationReport,
    LeadLagPair,
)
from engine.analytics.correlation.regime_detector import (
    MarketRegime,
    RegimeDetector,
    RegimeReport,
)

__version__ = "6.0.0"

__all__ = [
    "CorrelationAnalyzer",
    "CorrelationReport",
    "LeadLagPair",
    "MarketRegime",
    "RegimeDetector",
    "RegimeReport",
]
