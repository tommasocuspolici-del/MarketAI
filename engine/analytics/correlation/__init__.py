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
from engine.analytics.correlation.correlation_signal_generator import (
    CorrelationSignalGenerator,
    CorrelationSignalResult,
)
from engine.analytics.correlation.dcc_garch import DCCGARCHAnalyzer

__version__ = "8.1.0"

__all__ = [
    "CorrelationAnalyzer",
    "CorrelationReport",
    "LeadLagPair",
    "MarketRegime",
    "RegimeDetector",
    "RegimeReport",
    "CorrelationSignalGenerator",
    "CorrelationSignalResult",
    "DCCGARCHAnalyzer",
]
