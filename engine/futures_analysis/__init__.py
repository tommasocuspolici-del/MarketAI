"""Futures Analysis Engine — Settimana 5 Roadmap Unificata.

Moduli:
  · RollAnalyzer:              term structure (backwardation/contango) + roll yield
  · BasisAnalyzer:             basis = futures_close - spot_etf_close
  · OpenInterestAnalyzer:      4 segnali OI/prezzo (Schwager 1984)
  · CommodityRegimeClassifier: regime aggregato da roll + basis + OI
"""
from __future__ import annotations

from engine.futures_analysis.basis_analyzer import BasisAnalyzer
from engine.futures_analysis.commodity_regime import CommodityRegimeClassifier
from engine.futures_analysis.open_interest_analyzer import OpenInterestAnalyzer
from engine.futures_analysis.roll_analyzer import RollAnalyzer
from engine.futures_analysis.schemas import (
    BasisResult,
    CommodityAnalysis,
    CommodityRegime,
    OISignal,
    OpenInterestResult,
    RollYieldResult,
    TermStructure,
)

__version__ = "1.0.0"

__all__ = [
    "BasisAnalyzer",
    "BasisResult",
    "CommodityAnalysis",
    "CommodityRegime",
    "CommodityRegimeClassifier",
    "OISignal",
    "OpenInterestAnalyzer",
    "OpenInterestResult",
    "RollAnalyzer",
    "RollYieldResult",
    "TermStructure",
]
