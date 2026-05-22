from __future__ import annotations

import math
import pytest
import numpy as np

from engine.analytics.forecasting.scenario_tree_builder import (
    ScenarioTreeBuilder,
    ScenarioTree,
    Scenario,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def builder() -> ScenarioTreeBuilder:
    return ScenarioTreeBuilder()


def _make_inputs(base: float = 100.0) -> tuple[str, float, dict, dict]:
    horizons = [30, 60, 90]
    point_forecast = {h: base * (1 + 0.005 * i) for i, h in enumerate(horizons)}
    volatility = {h: base * 0.02 for h in horizons}
    return "SPY", base, point_forecast, volatility


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

class TestInstantiation:
    def test_instantiates(self) -> None:
        b = ScenarioTreeBuilder()
        assert isinstance(b, ScenarioTreeBuilder)


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

class TestBuild:
    def test_returns_scenario_tree(self, builder: ScenarioTreeBuilder) -> None:
        asset, base, pf, vol = _make_inputs()
        tree = builder.build(asset, base, pf, vol)
        assert isinstance(tree, ScenarioTree)

    def test_asset_matches_input(self, builder: ScenarioTreeBuilder) -> None:
        asset, base, pf, vol = _make_inputs()
        tree = builder.build(asset, base, pf, vol)
        assert tree.asset == asset

    def test_base_value_stored(self, builder: ScenarioTreeBuilder) -> None:
        asset, base, pf, vol = _make_inputs()
        tree = builder.build(asset, base, pf, vol)
        assert tree.base_value == base

    def test_three_scenarios(self, builder: ScenarioTreeBuilder) -> None:
        asset, base, pf, vol = _make_inputs()
        tree = builder.build(asset, base, pf, vol)
        assert len(tree.scenarios) == 3

    def test_scenario_names(self, builder: ScenarioTreeBuilder) -> None:
        asset, base, pf, vol = _make_inputs()
        tree = builder.build(asset, base, pf, vol)
        names = {s.name for s in tree.scenarios}
        assert names == {"bear", "base", "bull"}

    def test_probabilities_sum_to_one(self, builder: ScenarioTreeBuilder) -> None:
        asset, base, pf, vol = _make_inputs()
        tree = builder.build(asset, base, pf, vol)
        total_prob = sum(s.probability for s in tree.scenarios)
        assert math.isclose(total_prob, 1.0, rel_tol=1e-6)

    def test_bull_forecast_higher_than_bear(self, builder: ScenarioTreeBuilder) -> None:
        asset, base, pf, vol = _make_inputs(base=100.0)
        tree = builder.build(asset, base, pf, vol)
        bear_scenario = next(s for s in tree.scenarios if s.name == "bear")
        bull_scenario = next(s for s in tree.scenarios if s.name == "bull")
        for h in pf.keys():
            assert bull_scenario.forecasts[h] > bear_scenario.forecasts[h]

    def test_base_scenario_between_bear_bull(self, builder: ScenarioTreeBuilder) -> None:
        asset, base, pf, vol = _make_inputs(base=100.0)
        tree = builder.build(asset, base, pf, vol)
        bear = next(s for s in tree.scenarios if s.name == "bear")
        base_s = next(s for s in tree.scenarios if s.name == "base")
        bull = next(s for s in tree.scenarios if s.name == "bull")
        for h in pf.keys():
            assert bear.forecasts[h] <= base_s.forecasts[h] <= bull.forecasts[h]

    def test_generated_at_is_string(self, builder: ScenarioTreeBuilder) -> None:
        asset, base, pf, vol = _make_inputs()
        tree = builder.build(asset, base, pf, vol)
        assert isinstance(tree.generated_at, str)
        assert len(tree.generated_at) > 0

    def test_scenarios_have_description(self, builder: ScenarioTreeBuilder) -> None:
        asset, base, pf, vol = _make_inputs()
        tree = builder.build(asset, base, pf, vol)
        for s in tree.scenarios:
            assert isinstance(s.description, str)
            assert len(s.description) > 0

    def test_scenarios_have_positive_probability(self, builder: ScenarioTreeBuilder) -> None:
        asset, base, pf, vol = _make_inputs()
        tree = builder.build(asset, base, pf, vol)
        for s in tree.scenarios:
            assert s.probability > 0.0


# ---------------------------------------------------------------------------
# Regime probability adjustments
# ---------------------------------------------------------------------------

class TestRegimeProbabilities:
    def test_contraction_shifts_toward_bear(self, builder: ScenarioTreeBuilder) -> None:
        asset, base, pf, vol = _make_inputs()
        tree = builder.build(asset, base, pf, vol, current_regime="contraction")
        bear = next(s for s in tree.scenarios if s.name == "bear")
        assert bear.probability > 0.25  # higher than default 25%

    def test_expansion_has_lower_bear_prob(self, builder: ScenarioTreeBuilder) -> None:
        asset, base, pf, vol = _make_inputs()
        tree = builder.build(asset, base, pf, vol, current_regime="expansion")
        bear = next(s for s in tree.scenarios if s.name == "bear")
        assert bear.probability == pytest.approx(0.20)

    def test_recovery_has_higher_bull_prob(self, builder: ScenarioTreeBuilder) -> None:
        asset, base, pf, vol = _make_inputs()
        tree = builder.build(asset, base, pf, vol, current_regime="recovery")
        bull = next(s for s in tree.scenarios if s.name == "bull")
        assert bull.probability == pytest.approx(0.35)

    def test_unknown_regime_uses_default_probs(self, builder: ScenarioTreeBuilder) -> None:
        asset, base, pf, vol = _make_inputs()
        tree = builder.build(asset, base, pf, vol, current_regime="unknown_xyz")
        bear = next(s for s in tree.scenarios if s.name == "bear")
        bull = next(s for s in tree.scenarios if s.name == "bull")
        base_s = next(s for s in tree.scenarios if s.name == "base")
        assert math.isclose(bear.probability, 0.25, rel_tol=1e-6)
        assert math.isclose(bull.probability, 0.25, rel_tol=1e-6)
        assert math.isclose(base_s.probability, 0.50, rel_tol=1e-6)

    def test_all_regimes_sum_to_one(self, builder: ScenarioTreeBuilder) -> None:
        asset, base, pf, vol = _make_inputs()
        for regime in ("expansion", "slowdown", "contraction", "recovery", "stagflation"):
            tree = builder.build(asset, base, pf, vol, current_regime=regime)
            total = sum(s.probability for s in tree.scenarios)
            assert math.isclose(total, 1.0, rel_tol=1e-6), f"Failed for regime={regime}"
