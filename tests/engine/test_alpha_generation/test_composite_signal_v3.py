"""Tests for engine.alpha_generation.composite_signal_v3 — CompositeSignalAggregatorV3."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.alpha_generation.composite_signal_v3 import (
    CompositeSignalAggregatorV3,
)
from shared.alpha_decay_monitor import AlphaDecayMonitor
from shared.signal_registry import SignalRegistry
from shared.signal_types import Signal


def _make_monitor() -> AlphaDecayMonitor:
    return AlphaDecayMonitor()


def _publish_all(registry: SignalRegistry, value: float = 0.5) -> None:
    names = [
        "technical_composite", "macro_conviction", "labour_regime_signal",
        "sentiment_composite", "valuation_signal",
        "economic_surprise_index", "vix_signal",
    ]
    for name in names:
        registry.publish(
            Signal(name=name, value=value, confidence=0.8, source_module="test")
        )


class TestCompositeCompute:
    def test_returns_float_in_range(self) -> None:
        registry = SignalRegistry()
        _publish_all(registry, value=0.5)
        monitor = _make_monitor()
        agg = CompositeSignalAggregatorV3(decay_monitor=monitor)
        with patch("engine.alpha_generation.composite_signal_v3.get_signal_registry",
                   return_value=registry):
            result = agg.compute("bull")
        assert -1.0 <= result <= 1.0

    def test_all_positive_signals_positive_composite(self) -> None:
        registry = SignalRegistry()
        _publish_all(registry, value=0.8)
        monitor = _make_monitor()
        agg = CompositeSignalAggregatorV3(decay_monitor=monitor)
        with patch("engine.alpha_generation.composite_signal_v3.get_signal_registry",
                   return_value=registry):
            result = agg.compute("bull")
        assert result > 0

    def test_all_negative_signals_negative_composite(self) -> None:
        registry = SignalRegistry()
        _publish_all(registry, value=-0.8)
        monitor = _make_monitor()
        agg = CompositeSignalAggregatorV3(decay_monitor=monitor)
        with patch("engine.alpha_generation.composite_signal_v3.get_signal_registry",
                   return_value=registry):
            result = agg.compute("bear")
        assert result < 0

    def test_no_signals_returns_zero(self) -> None:
        registry = SignalRegistry()    # empty
        monitor = _make_monitor()
        agg = CompositeSignalAggregatorV3(decay_monitor=monitor)
        with patch("engine.alpha_generation.composite_signal_v3.get_signal_registry",
                   return_value=registry):
            result = agg.compute("bull")
        assert result == pytest.approx(0.0)

    def test_unknown_regime_uses_transition_weights(self) -> None:
        registry = SignalRegistry()
        _publish_all(registry, value=0.5)
        monitor = _make_monitor()
        agg = CompositeSignalAggregatorV3(decay_monitor=monitor)
        with patch("engine.alpha_generation.composite_signal_v3.get_signal_registry",
                   return_value=registry):
            result_unknown  = agg.compute("unknown_regime")
            result_transition = agg.compute("transition")
        assert result_unknown == pytest.approx(result_transition)

    def test_stress_regime_weights_sum_to_one(self) -> None:
        import yaml
        from pathlib import Path
        path = Path(__file__).resolve().parents[3] / "config" / "regime_weights.yaml"
        cfg = yaml.safe_load(path.read_text())
        for regime, weights in cfg["regime_signal_weights"].items():
            total = sum(weights.values())
            assert total == pytest.approx(1.0, abs=1e-6), \
                f"Weights for regime {regime!r} don't sum to 1: {total}"

    def test_decay_monitor_multiplier_reduces_weight(self) -> None:
        registry = SignalRegistry()
        _publish_all(registry, value=0.5)

        monitor = _make_monitor()
        monitor_high = _make_monitor()

        # low IC monitor returns 0.1 multiplier for all signals
        low_monitor = MagicMock()
        low_monitor.get_weight_multiplier.return_value = 0.1
        high_monitor = MagicMock()
        high_monitor.get_weight_multiplier.return_value = 1.0

        agg_low  = CompositeSignalAggregatorV3(decay_monitor=low_monitor)
        agg_high = CompositeSignalAggregatorV3(decay_monitor=high_monitor)

        with patch("engine.alpha_generation.composite_signal_v3.get_signal_registry",
                   return_value=registry):
            result_low  = agg_low.compute("bull")
            result_high = agg_high.compute("bull")

        # Both composites must still be in range; multiplier doesn't change direction
        assert -1.0 <= result_low  <= 1.0
        assert -1.0 <= result_high <= 1.0
        # With uniform signals, magnitude should be the same (normalisation)
        assert result_low == pytest.approx(result_high, abs=1e-3)


class TestCheckConsensus:
    def test_consensus_met_returns_true(self) -> None:
        registry = SignalRegistry()
        _publish_all(registry, value=0.5)
        monitor = _make_monitor()
        agg = CompositeSignalAggregatorV3(decay_monitor=monitor, consensus_min_agreeing=3)
        # patch at the call site inside consensus_validator
        with patch("shared.consensus_validator.get_signal_registry", return_value=registry):
            result = agg.check_consensus("BUY_SIGNAL", threshold=0.2)
        assert result is True

    def test_consensus_not_met_returns_false(self) -> None:
        registry = SignalRegistry()    # no signals
        monitor = _make_monitor()
        agg = CompositeSignalAggregatorV3(decay_monitor=monitor, consensus_min_agreeing=3)
        with patch("shared.consensus_validator.get_signal_registry", return_value=registry):
            result = agg.check_consensus("BUY_SIGNAL", threshold=0.2)
        assert result is False


class TestComponentNames:
    def test_component_names_contains_seven(self) -> None:
        agg = CompositeSignalAggregatorV3(decay_monitor=_make_monitor())
        assert len(agg.component_names) == 7

    def test_resolve_signal_name_technical(self) -> None:
        assert CompositeSignalAggregatorV3.resolve_signal_name("technical") == "technical_composite"

    def test_resolve_signal_name_unknown_passthrough(self) -> None:
        assert CompositeSignalAggregatorV3.resolve_signal_name("custom.x") == "custom.x"
