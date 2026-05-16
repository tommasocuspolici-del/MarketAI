"""Tests for shared.consensus_validator — ConsensusValidator (QC-3)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from shared.consensus_validator import (
    DEFAULT_MIN_AGREEING,
    ConsensusResult,
    ConsensusValidator,
)
from shared.signal_registry import SignalRegistry
from shared.signal_types import Signal


def _publish(registry: SignalRegistry, name: str, value: float) -> None:
    registry.publish(Signal(name=name, value=value, confidence=0.8, source_module="test"))


class TestConsensusValidatorBuySignal:
    def test_consensus_met_when_enough_agree(self) -> None:
        reg = SignalRegistry()
        _publish(reg, "a", 0.5)
        _publish(reg, "b", 0.6)
        _publish(reg, "c", 0.4)
        v = ConsensusValidator(min_agreeing=3)
        with patch("shared.consensus_validator.get_signal_registry", return_value=reg):
            result = v.check("BUY_SIGNAL", ["a", "b", "c"], threshold=0.2)
        assert result.consensus_met is True
        assert result.agreeing_count == 3

    def test_consensus_not_met_when_too_few(self) -> None:
        reg = SignalRegistry()
        _publish(reg, "a", 0.5)
        _publish(reg, "b", -0.5)   # disagreeing
        _publish(reg, "c", 0.05)   # below threshold
        v = ConsensusValidator(min_agreeing=3)
        with patch("shared.consensus_validator.get_signal_registry", return_value=reg):
            result = v.check("BUY_SIGNAL", ["a", "b", "c"], threshold=0.2)
        assert result.consensus_met is False

    def test_sell_signal_requires_negative_values(self) -> None:
        reg = SignalRegistry()
        _publish(reg, "a", -0.5)
        _publish(reg, "b", -0.6)
        _publish(reg, "c", -0.3)
        v = ConsensusValidator(min_agreeing=3)
        with patch("shared.consensus_validator.get_signal_registry", return_value=reg):
            result = v.check("SELL_SIGNAL", ["a", "b", "c"], threshold=0.2)
        assert result.consensus_met is True

    def test_sell_signal_positive_values_do_not_agree(self) -> None:
        reg = SignalRegistry()
        _publish(reg, "a", 0.5)
        v = ConsensusValidator(min_agreeing=1)
        with patch("shared.consensus_validator.get_signal_registry", return_value=reg):
            result = v.check("SELL_SIGNAL", ["a"], threshold=0.2)
        assert result.consensus_met is False

    def test_risk_alert_any_direction_counts(self) -> None:
        reg = SignalRegistry()
        _publish(reg, "a", 0.5)    # positive
        _publish(reg, "b", -0.5)   # negative — both count for RISK_ALERT
        v = ConsensusValidator(min_agreeing=2)
        with patch("shared.consensus_validator.get_signal_registry", return_value=reg):
            result = v.check("RISK_ALERT", ["a", "b"], threshold=0.2)
        assert result.consensus_met is True


class TestConsensusValidatorMissingSignals:
    def test_missing_signal_is_skipped(self) -> None:
        reg = SignalRegistry()
        _publish(reg, "a", 0.5)
        v = ConsensusValidator(min_agreeing=2)
        with patch("shared.consensus_validator.get_signal_registry", return_value=reg):
            result = v.check("BUY_SIGNAL", ["a", "missing"], threshold=0.2)
        assert result.agreeing_count == 1
        assert result.consensus_met is False

    def test_no_signals_available(self) -> None:
        reg = SignalRegistry()
        v = ConsensusValidator(min_agreeing=1)
        with patch("shared.consensus_validator.get_signal_registry", return_value=reg):
            result = v.check("BUY_SIGNAL", ["x", "y"], threshold=0.2)
        assert result.consensus_met is False
        assert result.agreeing_count == 0


class TestConsensusResultFields:
    def test_agreeing_signals_tuple_contains_agreeing_names(self) -> None:
        reg = SignalRegistry()
        _publish(reg, "a", 0.5)
        _publish(reg, "b", 0.1)   # below threshold
        v = ConsensusValidator(min_agreeing=1)
        with patch("shared.consensus_validator.get_signal_registry", return_value=reg):
            result = v.check("BUY_SIGNAL", ["a", "b"], threshold=0.2)
        assert "a" in result.agreeing_signals
        assert "b" not in result.agreeing_signals

    def test_required_count_from_constructor(self) -> None:
        reg = SignalRegistry()
        v = ConsensusValidator(min_agreeing=5)
        with patch("shared.consensus_validator.get_signal_registry", return_value=reg):
            result = v.check("BUY_SIGNAL", [], threshold=0.2)
        assert result.required_count == 5

    def test_default_min_agreeing_used_when_none(self) -> None:
        reg = SignalRegistry()
        v = ConsensusValidator()   # no explicit min_agreeing
        with patch("shared.consensus_validator.get_signal_registry", return_value=reg):
            result = v.check("BUY_SIGNAL", [], threshold=0.2)
        assert result.required_count == DEFAULT_MIN_AGREEING["BUY_SIGNAL"]


class TestDefaultMinAgreeing:
    def test_defaults_defined(self) -> None:
        assert DEFAULT_MIN_AGREEING["BUY_SIGNAL"]  == 3
        assert DEFAULT_MIN_AGREEING["SELL_SIGNAL"] == 3
        assert DEFAULT_MIN_AGREEING["RISK_ALERT"]  == 2
        assert DEFAULT_MIN_AGREEING["REBALANCE"]   == 4
