"""Tests for ConsensusSignalValidator (#9 QC) — dedicated file.

DoD: < 3 segnali concordanti → consensus_signal_validator = 0.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from custom_indicators.library.consensus_signal_validator import (
    ConsensusSignalValidator,
    ConsensusResult,
    _TRACKED_SIGNALS,
)
from shared.signal_registry import SignalRegistry
from shared.signal_types import Signal


def _reg(**signals: float) -> SignalRegistry:
    reg = SignalRegistry()
    for name, val in signals.items():
        reg.publish(Signal(name=name, value=val, confidence=0.8, source_module="test"))
    return reg


_PATCH = "custom_indicators.library.consensus_signal_validator.get_signal_registry"


class TestConsensusThreshold:
    """DoD: < 3 signals → value = 0."""

    @pytest.mark.parametrize("n_bullish,expected_zero", [
        (0, True),
        (1, True),
        (2, True),
        (3, False),   # exactly 3 → consensus reached
        (4, False),
        (5, False),
    ])
    def test_min_agreeing_3(self, n_bullish, expected_zero):
        signals = {n: 0.5 for n in list(_TRACKED_SIGNALS)[:n_bullish]}
        val = ConsensusSignalValidator(min_agreeing=3, direction_threshold=0.15)
        with patch(_PATCH, return_value=_reg(**signals)):
            r = val.compute()
        if expected_zero:
            assert r.consensus_value == pytest.approx(0.0), (
                f"Expected 0 for n_bullish={n_bullish}, got {r.consensus_value}"
            )
            assert not r.consensus_reached
        else:
            assert r.consensus_reached

    def test_exactly_2_bullish_no_consensus(self):
        reg = _reg(technical_composite=0.5, macro_conviction=0.4)
        val = ConsensusSignalValidator(min_agreeing=3)
        with patch(_PATCH, return_value=reg):
            r = val.compute()
        assert r.consensus_value == pytest.approx(0.0)
        assert r.direction == "no_consensus"

    def test_custom_min_agreeing_2(self):
        reg = _reg(technical_composite=0.5, macro_conviction=0.4)
        val = ConsensusSignalValidator(min_agreeing=2, direction_threshold=0.15)
        with patch(_PATCH, return_value=reg):
            r = val.compute()
        assert r.consensus_reached
        assert r.direction == "bullish"


class TestConsensusDirections:
    def test_bullish_direction(self):
        signals = {n: 0.5 for n in list(_TRACKED_SIGNALS)[:4]}
        val = ConsensusSignalValidator(min_agreeing=3)
        with patch(_PATCH, return_value=_reg(**signals)):
            r = val.compute()
        assert r.direction == "bullish"
        assert r.consensus_value > 0

    def test_bearish_direction(self):
        signals = {n: -0.5 for n in list(_TRACKED_SIGNALS)[:4]}
        val = ConsensusSignalValidator(min_agreeing=3)
        with patch(_PATCH, return_value=_reg(**signals)):
            r = val.compute()
        assert r.direction == "bearish"
        assert r.consensus_value < 0

    def test_mixed_no_consensus(self):
        signals = {
            list(_TRACKED_SIGNALS)[0]: 0.6,
            list(_TRACKED_SIGNALS)[1]: -0.6,
            list(_TRACKED_SIGNALS)[2]: 0.7,
            list(_TRACKED_SIGNALS)[3]: -0.7,
        }
        val = ConsensusSignalValidator(min_agreeing=3)
        with patch(_PATCH, return_value=_reg(**signals)):
            r = val.compute()
        assert r.direction == "no_consensus"

    def test_neutral_signals_counted(self):
        # Signals within direction_threshold count as neutral
        signals = {n: 0.05 for n in list(_TRACKED_SIGNALS)[:4]}
        val = ConsensusSignalValidator(min_agreeing=3, direction_threshold=0.15)
        with patch(_PATCH, return_value=_reg(**signals)):
            r = val.compute()
        assert r.n_neutral >= 4

    def test_consensus_value_in_range(self):
        signals = {n: 0.9 for n in _TRACKED_SIGNALS}
        val = ConsensusSignalValidator(min_agreeing=3)
        with patch(_PATCH, return_value=_reg(**signals)):
            r = val.compute()
        assert -1.0 <= r.consensus_value <= 1.0

    def test_agreeing_signals_list(self):
        signals = {n: 0.5 for n in list(_TRACKED_SIGNALS)[:4]}
        val = ConsensusSignalValidator(min_agreeing=3)
        with patch(_PATCH, return_value=_reg(**signals)):
            r = val.compute()
        assert len(r.agreeing_signals) >= 3
        assert r.consensus_reached

    def test_agreeing_signals_empty_when_no_consensus(self):
        val = ConsensusSignalValidator(min_agreeing=3)
        with patch(_PATCH, return_value=_reg()):
            r = val.compute()
        assert r.agreeing_signals == []


class TestConsensusToSignal:
    def test_signal_name(self):
        val = ConsensusSignalValidator()
        with patch(_PATCH, return_value=_reg()):
            s = val.to_signal(val.compute())
        assert s.name == "custom.consensus_signal_validator"

    def test_signal_value_zero_when_no_consensus(self):
        val = ConsensusSignalValidator(min_agreeing=3)
        with patch(_PATCH, return_value=_reg()):
            snap = val.compute()
            s = val.to_signal(snap)
        assert s.value == pytest.approx(0.0)

    def test_signal_value_positive_bullish(self):
        signals = {n: 0.5 for n in list(_TRACKED_SIGNALS)[:4]}
        val = ConsensusSignalValidator(min_agreeing=3)
        with patch(_PATCH, return_value=_reg(**signals)):
            snap = val.compute()
            s = val.to_signal(snap)
        assert s.value > 0

    def test_metadata_direction_present(self):
        val = ConsensusSignalValidator()
        with patch(_PATCH, return_value=_reg()):
            s = val.to_signal(val.compute())
        assert "direction" in s.metadata
        assert "reached" in s.metadata
        assert "agreeing" in s.metadata

    def test_signal_is_frozen(self):
        val = ConsensusSignalValidator()
        with patch(_PATCH, return_value=_reg()):
            s = val.to_signal(val.compute())
        with pytest.raises(Exception):
            s.value = 0.0  # type: ignore[misc]

    def test_result_is_dataclass(self):
        val = ConsensusSignalValidator()
        with patch(_PATCH, return_value=_reg()):
            r = val.compute()
        assert isinstance(r, ConsensusResult)
