"""Backtesting strategies package."""
from __future__ import annotations

from engine.backtesting.strategies.combined import CombinedStrategy
from engine.backtesting.strategies.ma_cross import MovingAverageCrossover
from engine.backtesting.strategies.macro_filter import MacroFilter
from engine.backtesting.strategies.momentum import Momentum
from engine.backtesting.strategies.rsi import RSIMeanReversion, compute_rsi

__version__ = "6.0.0"

__all__ = [
    "CombinedStrategy",
    "MacroFilter",
    "Momentum",
    "MovingAverageCrossover",
    "RSIMeanReversion",
    "compute_rsi",
]
