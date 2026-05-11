"""Backtesting package — strategies + engine + performance + persistence."""
from __future__ import annotations

from engine.backtesting.engine import (
    MIN_FEES,
    MIN_QUALITY_FOR_BACKTEST,
    MIN_SLIPPAGE,
    BacktestEngine,
    BacktestResult,
    WalkForwardResult,
)
from engine.backtesting.performance import PerformanceReport, compute_performance_report
from engine.backtesting.results_repo import BacktestResultsRepository, get_backtest_results_repo
from engine.backtesting.strategy import Strategy, StrategySignal

__version__ = "6.0.0"

__all__ = [
    "MIN_FEES",
    "MIN_QUALITY_FOR_BACKTEST",
    "MIN_SLIPPAGE",
    "BacktestEngine",
    "BacktestResult",
    "BacktestResultsRepository",
    "PerformanceReport",
    "Strategy",
    "StrategySignal",
    "WalkForwardResult",
    "compute_performance_report",
    "get_backtest_results_repo",
]
