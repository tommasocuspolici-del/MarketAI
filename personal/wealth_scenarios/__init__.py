"""Wealth scenarios sub-package — Monte Carlo + retirement (FIRE)."""
from __future__ import annotations

from personal.wealth_scenarios.retirement_simulator import (
    FIREResult,
    RetirementSimulator,
)
from personal.wealth_scenarios.simulator import (
    WealthSimulationResult,
    WealthSimulator,
)

__version__ = "6.0.0"

__all__ = [
    "FIREResult",
    "RetirementSimulator",
    "WealthSimulationResult",
    "WealthSimulator",
]
