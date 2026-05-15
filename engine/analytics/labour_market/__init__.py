"""engine.analytics.labour_market — Labour Market Engine (Blocco B).

ROADMAP_ANALISI_MERCATO_v4 — Blocco 1.
Struttura moduli:
  · jolts_fetcher.py            — JOLTSFetcher (FRED fetch + DuckDB persist)
  · claims_fetcher.py           — ClaimsFetcher (FRED fetch + DuckDB persist)
  · payroll_fetcher.py          — PayrollFetcher (FRED fetch + DuckDB persist)
  · jolts_analyzer.py           — JOLTSAnalyzer (Beveridge curve + segnali)
  · claims_cycle_detector.py    — ClaimsCycleDetector (4wk MA + regime)
  · payroll_decomposer.py       — PayrollDecomposer (cyclical/defensive split)
  · labour_regime_classifier.py — LabourRegimeClassifier (composite regime)
  · labour_forecast_engine.py   — LabourForecastEngine (ARIMA + Ridge 1M/3M/6M)
  · schemas.py                  — Pandera schemas + dataclasses
"""
from __future__ import annotations

from engine.analytics.labour_market.jolts_analyzer import (
    JOLTSAnalyzer,
    JOLTSSignal,
)
from engine.analytics.labour_market.claims_cycle_detector import (
    ClaimsCycleDetector,
    ClaimsCycleSignal,
)
from engine.analytics.labour_market.payroll_decomposer import (
    PayrollDecomposer,
    PayrollSignal,
)
from engine.analytics.labour_market.labour_regime_classifier import (
    LabourRegimeClassifier,
    LabourRegimeResult,
)
from engine.analytics.labour_market.labour_forecast_engine import (
    LabourForecastEngine,
)
from engine.analytics.labour_market.schemas import (
    LabourForecastResult,
    ForecastBundle,
    JOLTSOutputSchema,
    ClaimsOutputSchema,
    PayrollOutputSchema,
)

__version__ = "1.0.0"

__all__ = [
    "JOLTSAnalyzer",
    "JOLTSSignal",
    "ClaimsCycleDetector",
    "ClaimsCycleSignal",
    "PayrollDecomposer",
    "PayrollSignal",
    "LabourRegimeClassifier",
    "LabourRegimeResult",
    "LabourForecastEngine",
    "LabourForecastResult",
    "ForecastBundle",
    "JOLTSOutputSchema",
    "ClaimsOutputSchema",
    "PayrollOutputSchema",
]
