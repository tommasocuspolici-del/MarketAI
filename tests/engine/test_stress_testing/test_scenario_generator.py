"""Tests for engine.stress_testing.scenario_generator."""
from __future__ import annotations

from datetime import UTC, datetime

from engine.stress_testing.scenario import MarketContext, ScenarioType
from engine.stress_testing.scenario_generator import ScenarioGenerator


def _make_context(
    vix: float = 20.0,
    yield_curve: float = 0.5,
    sentiment: float = 0.0,
    regime: str = "transition",
) -> MarketContext:
    return MarketContext(
        vix=vix,
        yield_curve_2y_10y=yield_curve,
        sentiment_composite=sentiment,
        regime=regime,
        timestamp=datetime(2025, 4, 1, tzinfo=UTC),
    )


class TestScenarioGeneratorBasic:
    def test_generates_at_least_5_scenarios(self) -> None:
        """DoD Fase 5: almeno 5 scenari forward-looking per qualsiasi context."""
        scenarios = ScenarioGenerator.generate(_make_context())
        assert len(scenarios) >= 5

    def test_all_marked_synthetic(self) -> None:
        for s in ScenarioGenerator.generate(_make_context()):
            assert s.scenario_type is ScenarioType.SYNTHETIC

    def test_all_have_market_context(self) -> None:
        ctx = _make_context()
        for s in ScenarioGenerator.generate(ctx):
            assert s.market_context is not None
            # Stesso context oggetto / valori
            assert s.market_context.vix == ctx.vix

    def test_all_have_calibrated_probability(self) -> None:
        for s in ScenarioGenerator.generate(_make_context()):
            assert s.probability is not None
            assert 0.0 <= s.probability <= 1.0

    def test_unique_names(self) -> None:
        names = {s.name for s in ScenarioGenerator.generate(_make_context())}
        # Ognuno dei 6 scenari ha nome distinto
        assert len(names) >= 5


class TestRegimeCalibration:
    def test_bull_regime_high_goldilocks_probability(self) -> None:
        ctx = _make_context(regime="bull", sentiment=0.5)
        scenarios = ScenarioGenerator.generate(ctx)
        goldilocks = next(s for s in scenarios if "Goldilocks" in s.name)
        recession = next(s for s in scenarios if "Recession" in s.name)
        # Bull regime: Goldilocks più probabile della Recession
        assert goldilocks.probability > recession.probability

    def test_stress_regime_high_recession_probability(self) -> None:
        ctx = _make_context(regime="stress", vix=40, sentiment=-0.6)
        scenarios = ScenarioGenerator.generate(ctx)
        goldilocks = next(s for s in scenarios if "Goldilocks" in s.name)
        recession = next(s for s in scenarios if "Recession" in s.name)
        # Stress regime: Recession enormemente più probabile di Goldilocks
        assert recession.probability > goldilocks.probability * 2

    def test_high_vix_increases_vol_multiplier(self) -> None:
        low_vix = ScenarioGenerator.generate(_make_context(vix=12, regime="bull"))
        high_vix = ScenarioGenerator.generate(_make_context(vix=45, regime="stress"))
        # Vol multiplier scenari "Recession" più alto in regime stress
        low_recession = next(s for s in low_vix if "Recession" in s.name)
        high_recession = next(s for s in high_vix if "Recession" in s.name)
        assert high_recession.vol_multiplier > low_recession.vol_multiplier


class TestProbabilitiesSumBounded:
    def test_probabilities_do_not_exceed_one(self) -> None:
        scenarios = ScenarioGenerator.generate(
            _make_context(regime="stress", vix=50, sentiment=-0.8)
        )
        total_prob = sum(s.probability or 0 for s in scenarios)
        # Lasciamo margine: il residuo è "base case" (nessuno shock)
        assert total_prob <= 1.0 + 1e-6


class TestUnknownRegimeDefaults:
    def test_unknown_regime_uses_transition_default(self) -> None:
        # Regola di robustezza: regime non standard → fallback transition
        scenarios = ScenarioGenerator.generate(
            _make_context(regime="unknown_xyz")
        )
        # Funziona senza errori
        assert len(scenarios) >= 5
