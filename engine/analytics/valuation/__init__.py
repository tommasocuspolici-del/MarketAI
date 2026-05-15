"""Valuation Engine — P/E Ratio Multi-Indicatore.

ROADMAP_ANALISI_MERCATO_v4 — Blocco 3.
"""
from engine.analytics.valuation.schemas import (
    PEMetrics,
    ValuationLabel,
    ValuationSignalResult,
)
from engine.analytics.valuation.pe_calculator import PECalculator
from engine.analytics.valuation.pe_context_builder import PEContextBuilder
from engine.analytics.valuation.valuation_signal_generator import ValuationSignalGenerator
from engine.analytics.valuation.earnings_fetcher import EarningsFetcher, EarningsSnapshot
from engine.analytics.valuation.forward_estimates_fetcher import (
    ForwardEstimatesFetcher,
    ForwardEstimate,
)
from engine.analytics.valuation.equity_risk_premium import (
    EquityRiskPremium,
    ERPResult,
    ERPRegime,
)

__all__ = [
    "PEMetrics",
    "ValuationLabel",
    "ValuationSignalResult",
    "PECalculator",
    "PEContextBuilder",
    "ValuationSignalGenerator",
    "EarningsFetcher",
    "EarningsSnapshot",
    "ForwardEstimatesFetcher",
    "ForwardEstimate",
    "EquityRiskPremium",
    "ERPResult",
    "ERPRegime",
]
