"""Stress testing package — historical + synthetic scenarios + tester."""
from __future__ import annotations

from engine.stress_testing.historical_scenarios import (
    build_covid_2020,
    build_dot_com_2000_2002,
    build_global_financial_crisis_2008,
    build_historical_scenarios,
    build_rate_hike_2022,
)
from engine.stress_testing.scenario import (
    MarketContext,
    ScenarioOutcome,
    ScenarioType,
    StressScenario,
)
from engine.stress_testing.scenario_generator import ScenarioGenerator
from engine.stress_testing.scenarios_repo import (
    StressScenariosRepository,
    get_stress_scenarios_repo,
)
from engine.stress_testing.tester import StressAlert, StressTester, StressTestReport

__version__ = "6.0.0"

__all__ = [
    "MarketContext",
    "ScenarioGenerator",
    "ScenarioOutcome",
    "ScenarioType",
    "StressAlert",
    "StressScenario",
    "StressScenariosRepository",
    "StressTestReport",
    "StressTester",
    "build_covid_2020",
    "build_dot_com_2000_2002",
    "build_global_financial_crisis_2008",
    "build_historical_scenarios",
    "build_rate_hike_2022",
    "get_stress_scenarios_repo",
]
