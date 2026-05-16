"""Tests for ICWeightedEnsembleComposer — DoD: zero weight for IC < 0.02, weights sum to 1.0."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from engine.strategy_lab.ensemble_composer import EnsembleResult, ICWeightedEnsembleComposer
from shared.alpha_decay_monitor import AlphaDecayMonitor, IC_MIN_THRESHOLD


def _monitor_with_ic(ic_map: dict[str, float]) -> AlphaDecayMonitor:
    m = MagicMock(spec=AlphaDecayMonitor)
    def _check(sig_name: str):
        k = sig_name.removeprefix("strategy.")
        ic = ic_map.get(k)
        if ic is None:
            return None, "insufficient_data"
        flag = "ok" if ic >= 0.05 else "low_ic"
        return ic, flag
    m.check_decay.side_effect = _check
    return m


class TestWeightsSumToOne:
    def test_weights_sum_to_one_with_high_ic(self) -> None:
        """DoD: pesi sommano a 1.0."""
        monitor = _monitor_with_ic({"a": 0.10, "b": 0.08, "c": 0.06})
        composer = ICWeightedEnsembleComposer(monitor)
        result = composer.compose({"a": 0.5, "b": 0.3, "c": 0.2})
        total = sum(result.weights.values())
        assert total == pytest.approx(1.0, abs=1e-6)   # DoD invariant

    def test_weights_sum_to_one_with_mixed_ic(self) -> None:
        monitor = _monitor_with_ic({"a": 0.10, "b": 0.001, "c": 0.08})
        composer = ICWeightedEnsembleComposer(monitor)
        result = composer.compose({"a": 0.4, "b": -0.3, "c": 0.5})
        total = sum(result.weights.values())
        assert total == pytest.approx(1.0, abs=1e-6)

    def test_weights_sum_to_one_fallback(self) -> None:
        """All strategies zeroed → equal weights → still sums to 1.0."""
        monitor = _monitor_with_ic({"a": 0.001, "b": 0.001})
        composer = ICWeightedEnsembleComposer(monitor)
        result = composer.compose({"a": 0.5, "b": -0.5})
        total = sum(result.weights.values())
        assert total == pytest.approx(1.0, abs=1e-6)


class TestLowICZeroed:
    def test_strategy_with_ic_below_min_zeroed(self) -> None:
        """DoD: peso = 0 per strategia con IC < IC_MIN_THRESHOLD."""
        monitor = _monitor_with_ic({"good": 0.10, "bad": 0.001})
        composer = ICWeightedEnsembleComposer(monitor)
        result = composer.compose({"good": 0.5, "bad": 0.9})
        # "bad" should have weight 0 (IC < 0.02)
        assert result.weights["bad"] == pytest.approx(0.0, abs=1e-6)   # DoD

    def test_all_low_ic_triggers_fallback(self) -> None:
        monitor = _monitor_with_ic({"a": 0.001, "b": 0.001, "c": 0.001})
        composer = ICWeightedEnsembleComposer(monitor)
        result = composer.compose({"a": 0.5, "b": 0.5, "c": 0.5})
        assert result.fallback_used is True

    def test_n_zeroed_counted(self) -> None:
        monitor = _monitor_with_ic({"a": 0.10, "b": 0.001, "c": 0.001})
        composer = ICWeightedEnsembleComposer(monitor)
        result = composer.compose({"a": 0.5, "b": 0.3, "c": -0.2})
        assert result.n_zeroed == 2
        assert result.n_active == 1


class TestEnsembleSignal:
    def test_ensemble_in_range(self) -> None:
        monitor = _monitor_with_ic({"a": 0.10, "b": 0.08})
        composer = ICWeightedEnsembleComposer(monitor)
        result = composer.compose({"a": 1.0, "b": -1.0})
        assert -1.0 <= result.ensemble_signal <= 1.0

    def test_single_strategy_returns_its_signal(self) -> None:
        monitor = _monitor_with_ic({"only": 0.10})
        composer = ICWeightedEnsembleComposer(monitor)
        result = composer.compose({"only": 0.7})
        assert result.ensemble_signal == pytest.approx(0.7, abs=1e-4)

    def test_empty_signals_returns_zero(self) -> None:
        monitor = _monitor_with_ic({})
        composer = ICWeightedEnsembleComposer(monitor)
        result = composer.compose({})
        assert result.ensemble_signal == pytest.approx(0.0)


class TestRiskBlockedStrategies:
    def test_risk_blocked_strategy_zeroed(self) -> None:
        monitor = _monitor_with_ic({"risky": 0.15, "safe": 0.10})
        composer = ICWeightedEnsembleComposer(monitor)
        result = composer.compose(
            {"risky": 0.8, "safe": 0.4},
            risk_blocked={"risky"},
        )
        assert result.weights["risky"] == pytest.approx(0.0, abs=1e-6)
        assert result.weights["safe"] == pytest.approx(1.0, abs=1e-6)


class TestHighICDominates:
    def test_high_ic_gets_more_weight(self) -> None:
        monitor = _monitor_with_ic({"strong": 0.20, "weak": 0.05})
        composer = ICWeightedEnsembleComposer(monitor)
        result = composer.compose({"strong": 0.5, "weak": 0.5})
        assert result.weights["strong"] > result.weights["weak"]
