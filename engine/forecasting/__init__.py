"""Forecasting package — modelli predittivi su prezzi e indicatori macro.

Stato v7.1.2: solo SimpleForecaster (GBM 3-scenari, esplorativo).
Roadmap: ARIMA + Prophet + walk-forward backtesting nelle settimane 4-7
della Roadmap Unificata 2.0.
"""
from __future__ import annotations

from engine.forecasting.simple_forecaster import (
    ForecastResult,
    ForecastScenario,
    SimpleForecaster,
)

__version__ = "7.1.2"

__all__ = [
    "ForecastResult",
    "ForecastScenario",
    "SimpleForecaster",
]
