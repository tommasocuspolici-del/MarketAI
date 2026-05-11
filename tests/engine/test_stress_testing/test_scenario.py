"""Tests for engine.stress_testing.scenario."""
from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from engine.stress_testing.scenario import (
    MarketContext,
    ScenarioOutcome,
    ScenarioType,
    StressScenario,
)
from shared.exceptions import StressTestError


def _equity(n: int = 252, start: float = 10_000.0) -> pd.Series:
    """Simple linear equity curve for tests."""
    return pd.Series(np.linspace(start, start * 1.10, n), dtype="float64")


# ═══════════════════════════════════════════════════════════════════════════
# StressScenario validation
# ═══════════════════════════════════════════════════════════════════════════
class TestStressScenarioValidation:
    def test_valid_scenario_constructed(self) -> None:
        s = StressScenario(
            name="Test",
            scenario_type=ScenarioType.HISTORICAL,
            equity_shock_pct=-0.30,
            bond_shock_pct=0.05,
        )
        assert s.scenario_type is ScenarioType.HISTORICAL
        assert s.equity_shock_pct == -0.30
        # scenario_id auto-generato (UUID)
        assert len(s.scenario_id) > 0

    def test_equity_shock_out_of_range_raises(self) -> None:
        with pytest.raises(StressTestError, match="equity_shock_pct"):
            StressScenario(
                name="Bad",
                scenario_type=ScenarioType.HISTORICAL,
                equity_shock_pct=-1.5,
                bond_shock_pct=0.0,
            )

    def test_bond_shock_out_of_range_raises(self) -> None:
        with pytest.raises(StressTestError, match="bond_shock_pct"):
            StressScenario(
                name="Bad",
                scenario_type=ScenarioType.HISTORICAL,
                equity_shock_pct=-0.20,
                bond_shock_pct=2.0,
            )

    def test_invalid_vol_multiplier_raises(self) -> None:
        with pytest.raises(StressTestError, match="vol_multiplier"):
            StressScenario(
                name="Bad",
                scenario_type=ScenarioType.HISTORICAL,
                equity_shock_pct=-0.10,
                bond_shock_pct=0.0,
                vol_multiplier=-0.5,
            )

    def test_probability_out_of_range_raises(self) -> None:
        with pytest.raises(StressTestError, match="probability"):
            StressScenario(
                name="Bad",
                scenario_type=ScenarioType.SYNTHETIC,
                equity_shock_pct=-0.10,
                bond_shock_pct=0.0,
                probability=1.5,
            )


# ═══════════════════════════════════════════════════════════════════════════
# Scenario application
# ═══════════════════════════════════════════════════════════════════════════
class TestApplyToEquityCurve:
    def test_apply_produces_outcome(self) -> None:
        scenario = StressScenario(
            name="Mild Shock",
            scenario_type=ScenarioType.HISTORICAL,
            equity_shock_pct=-0.20,
            bond_shock_pct=0.05,
        )
        equity = _equity(60)
        outcome = scenario.apply_to_equity_curve(equity)

        assert isinstance(outcome, ScenarioOutcome)
        assert len(outcome.stressed_equity) == 60
        # Shock negativo produce final_loss negativo
        assert outcome.final_loss_pct < 0.0
        # max_loss_pct ≤ final_loss_pct (max drawdown è almeno la perdita finale)
        assert outcome.max_loss_pct <= outcome.final_loss_pct + 1e-9

    def test_zero_equity_weight_no_equity_impact(self) -> None:
        scenario = StressScenario(
            name="Equity Only",
            scenario_type=ScenarioType.HISTORICAL,
            equity_shock_pct=-0.50,
            bond_shock_pct=0.0,
            vol_multiplier=0.01,  # ridotto al minimo per stabilità del test
        )
        equity = _equity(60)
        # Con weight 0 sull'equity → quasi nessun impatto deterministico
        outcome = scenario.apply_to_equity_curve(
            equity, equity_weight=0.0, bond_weight=0.0
        )
        # Final loss vicino a zero (rumore residuo solamente)
        assert abs(outcome.final_loss_pct) < 0.05

    def test_short_curve_raises(self) -> None:
        scenario = StressScenario(
            name="X",
            scenario_type=ScenarioType.HISTORICAL,
            equity_shock_pct=-0.10,
            bond_shock_pct=0.0,
        )
        with pytest.raises(StressTestError, match="at least 2 points"):
            scenario.apply_to_equity_curve(pd.Series([100.0]))

    def test_invalid_weights_raise(self) -> None:
        scenario = StressScenario(
            name="X",
            scenario_type=ScenarioType.HISTORICAL,
            equity_shock_pct=-0.10,
            bond_shock_pct=0.0,
        )
        equity = _equity(30)
        with pytest.raises(StressTestError, match="weights"):
            scenario.apply_to_equity_curve(equity, equity_weight=0.7, bond_weight=0.5)

    def test_severity_classification(self) -> None:
        # Mild: max_loss ≥ -10%
        outcome = ScenarioOutcome(
            scenario=StressScenario(
                name="X", scenario_type=ScenarioType.HISTORICAL,
                equity_shock_pct=-0.05, bond_shock_pct=0.0,
            ),
            stressed_equity=pd.Series([100.0, 95.0]),
            max_loss_pct=-0.05,
            final_loss_pct=-0.05,
        )
        assert outcome.severity == "mild"

        # Moderate: -25% ≤ max_loss < -10%
        outcome2 = ScenarioOutcome(
            scenario=outcome.scenario,
            stressed_equity=pd.Series([100.0, 80.0]),
            max_loss_pct=-0.20,
            final_loss_pct=-0.20,
        )
        assert outcome2.severity == "moderate"

        # Severe
        outcome3 = ScenarioOutcome(
            scenario=outcome.scenario,
            stressed_equity=pd.Series([100.0, 60.0]),
            max_loss_pct=-0.40,
            final_loss_pct=-0.40,
        )
        assert outcome3.severity == "severe"

        # Extreme
        outcome4 = ScenarioOutcome(
            scenario=outcome.scenario,
            stressed_equity=pd.Series([100.0, 30.0]),
            max_loss_pct=-0.70,
            final_loss_pct=-0.70,
        )
        assert outcome4.severity == "extreme"


# ═══════════════════════════════════════════════════════════════════════════
# MarketContext
# ═══════════════════════════════════════════════════════════════════════════
class TestMarketContext:
    def test_to_dict_serializable(self) -> None:
        ctx = MarketContext(
            vix=22.5,
            yield_curve_2y_10y=-0.10,
            sentiment_composite=-0.3,
            regime="bear",
            timestamp=datetime(2025, 4, 1, tzinfo=UTC),
        )
        d = ctx.to_dict()
        assert d["vix"] == 22.5
        assert d["regime"] == "bear"
        # timestamp è serializzato come stringa ISO
        assert isinstance(d["timestamp"], str)

    def test_default_values(self) -> None:
        ctx = MarketContext(
            vix=15.0,
            yield_curve_2y_10y=0.50,
            sentiment_composite=0.4,
            regime="bull",
        )
        assert ctx.equity_volatility == 0.15
        assert ctx.risk_free_rate == 0.04


# ═══════════════════════════════════════════════════════════════════════════
# Scenario persistence dict
# ═══════════════════════════════════════════════════════════════════════════
class TestPersistenceDict:
    def test_historical_scenario_dict_no_context(self) -> None:
        scenario = StressScenario(
            name="GFC", scenario_type=ScenarioType.HISTORICAL,
            equity_shock_pct=-0.50, bond_shock_pct=0.10,
        )
        d = scenario.to_persistence_dict()
        # Storici: no market_context
        assert d["market_context"] is None
        assert d["scenario_type"] == "historical"

    def test_synthetic_scenario_dict_with_context(self) -> None:
        ctx = MarketContext(
            vix=20.0, yield_curve_2y_10y=0.0,
            sentiment_composite=0.0, regime="transition",
        )
        scenario = StressScenario(
            name="Synthetic", scenario_type=ScenarioType.SYNTHETIC,
            equity_shock_pct=-0.20, bond_shock_pct=0.0,
            market_context=ctx, probability=0.15,
        )
        d = scenario.to_persistence_dict()
        # Sintetici: market_context serializzato come JSON string
        assert d["market_context"] is not None
        assert isinstance(d["market_context"], str)
        assert d["probability"] == 0.15
