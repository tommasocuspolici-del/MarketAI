"""Tests for engine.stress_testing.historical_scenarios."""
from __future__ import annotations

import pytest

from engine.stress_testing.historical_scenarios import (
    build_covid_2020,
    build_dot_com_2000_2002,
    build_global_financial_crisis_2008,
    build_historical_scenarios,
    build_rate_hike_2022,
)
from engine.stress_testing.scenario import ScenarioType


class TestHistoricalScenarios:
    def test_returns_exactly_4_scenarios(self) -> None:
        """DoD Fase 5: 4 scenari storici implementati."""
        scenarios = build_historical_scenarios()
        assert len(scenarios) == 4

    def test_all_marked_historical(self) -> None:
        for s in build_historical_scenarios():
            assert s.scenario_type is ScenarioType.HISTORICAL

    def test_all_have_unique_ids(self) -> None:
        ids = {s.scenario_id for s in build_historical_scenarios()}
        assert len(ids) == 4

    def test_all_have_descriptions(self) -> None:
        for s in build_historical_scenarios():
            assert len(s.description) > 30, (
                f"scenario '{s.name}' missing description"
            )

    def test_no_probability_for_historical(self) -> None:
        """Storici non hanno probability (DoD: NULL per scenari storici)."""
        for s in build_historical_scenarios():
            assert s.probability is None


class TestSpecificScenarios:
    def test_gfc_2008_calibration(self) -> None:
        s = build_global_financial_crisis_2008()
        # S&P -57% peak-to-trough
        assert s.equity_shock_pct == pytest.approx(-0.57)
        # Treasuries +10%
        assert s.bond_shock_pct == pytest.approx(0.10)
        # Vol multiplier alto (VIX peak ~80)
        assert s.vol_multiplier >= 2.5

    def test_covid_2020_calibration(self) -> None:
        s = build_covid_2020()
        # S&P -34% in 33 trading days
        assert s.equity_shock_pct == pytest.approx(-0.34)
        # Bonds +8% flight-to-safety
        assert s.bond_shock_pct == pytest.approx(0.08)
        # VIX peak ~83
        assert s.vol_multiplier >= 3.0

    def test_rate_hike_2022_unique_pattern(self) -> None:
        """2022 è speciale: equity E bond entrambi negativi."""
        s = build_rate_hike_2022()
        assert s.equity_shock_pct < 0
        assert s.bond_shock_pct < 0  # Anomalia storica del 2022

    def test_dot_com_calibration(self) -> None:
        s = build_dot_com_2000_2002()
        # S&P -49% peak-to-trough
        assert s.equity_shock_pct == pytest.approx(-0.49)
        # Bonds rally as Fed cut rates
        assert s.bond_shock_pct > 0

    def test_each_scenario_has_distinct_name(self) -> None:
        names = {
            build_global_financial_crisis_2008().name,
            build_covid_2020().name,
            build_rate_hike_2022().name,
            build_dot_com_2000_2002().name,
        }
        assert len(names) == 4
