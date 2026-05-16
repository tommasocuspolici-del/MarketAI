"""Options Analytics Engine — v10.0.0 (ROADMAP v5 Blocco D, Lean MVP).

Modules:
  bs_calculator        — Black-Scholes price + Greeks (delta, gamma, vega, theta, rho)
  iv_solver            — Implied Volatility via Newton-Raphson
  vol_surface_builder  — Volatility surface from option chain
  strategy_builder     — P&L profiles: straddle, collar, covered_call, vertical spread
  expected_move        — Expected move = IV * spot * sqrt(T)
  mock_chain           — Synthetic option chain for lean MVP (no live data)

Feature flags:
  options_analytics:            false  — master switch (BS/IV/VolSurface/StrategyBuilder)
  options_live_chain:           false  — Finnhub live chain (opt-in)
  options_strategy_suggestions: true   — collar suggestion in P2
"""
from __future__ import annotations

from engine.options.bs_calculator import BSGreeks, BSResult, BlackScholesCalculator
from engine.options.collar_advisor import CollarAdvisor, CollarSuggestion
from engine.options.expected_move import ExpectedMoveCalculator, ExpectedMoveResult
from engine.options.iv_solver import IVResult, IVSolver
from engine.options.mock_chain import MockOptionsChain, OptionContract
from engine.options.strategy_builder import StrategyBuilder, StrategyResult
from engine.options.vol_surface_builder import VolSurface, VolSurfaceBuilder

__version__ = "10.0.0"

__all__ = [
    "BSGreeks",
    "BSResult",
    "BlackScholesCalculator",
    "CollarAdvisor",
    "CollarSuggestion",
    "ExpectedMoveCalculator",
    "ExpectedMoveResult",
    "IVResult",
    "IVSolver",
    "MockOptionsChain",
    "OptionContract",
    "StrategyBuilder",
    "StrategyResult",
    "VolSurface",
    "VolSurfaceBuilder",
]
