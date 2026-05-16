"""Integration: < 3 segnali concordanti → consensus_signal_validator = 0.

DoD (G.1):
  Verifica che: < 3 segnali concordanti → consensus_signal_validator = 0.

Pipeline testata:
  1. SignalRegistry.publish() → snapshot
  2. ConsensusSignalValidator.compute() legge dal registry
  3. < 3 concordanti → consensus_value = 0.0, consensus_reached = False
  4. Soglia configurabile: min_agreeing=2 funziona diversamente da 3
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from custom_indicators.library.consensus_signal_validator import (
    ConsensusSignalValidator,
    _TRACKED_SIGNALS,
)
from shared.signal_registry import SignalRegistry
from shared.signal_types import Signal


_PATCH = "custom_indicators.library.consensus_signal_validator.get_signal_registry"

_SIGNAL_NAMES: list[str] = list(_TRACKED_SIGNALS)


def _make_registry(signal_values: dict[str, float]) -> SignalRegistry:
    reg = SignalRegistry()
    for name, value in signal_values.items():
        reg.publish(Signal(
            name=name, value=value, confidence=0.8,
            source_module="integration_test",
        ))
    return reg


class TestConsensusGateThreshold:
    """DoD: < 3 segnali concordanti → output = 0."""

    @pytest.mark.parametrize("n_agreeing,expected_consensus", [
        (0, False),
        (1, False),
        (2, False),
        (3, True),   # exactly 3 → gate opens
        (4, True),
        (5, True),
        (7, True),
    ])
    def test_gate_opens_at_3(self, n_agreeing: int, expected_consensus: bool):
        """Gate opens if and only if n_agreeing >= 3."""
        signals = {_SIGNAL_NAMES[i]: 0.5
                   for i in range(min(n_agreeing, len(_SIGNAL_NAMES)))}
        reg = _make_registry(signals)
        val = ConsensusSignalValidator(min_agreeing=3, direction_threshold=0.15)
        with patch(_PATCH, return_value=reg):
            r = val.compute()
        assert r.consensus_reached == expected_consensus, (
            f"n_agreeing={n_agreeing}: expected reached={expected_consensus}, got {r.consensus_reached}"
        )
        if not expected_consensus:
            assert r.consensus_value == pytest.approx(0.0), (
                f"n_agreeing={n_agreeing}: consensus_value should be 0, got {r.consensus_value}"
            )

    def test_two_agreeing_value_is_zero(self):
        reg = _make_registry({
            _SIGNAL_NAMES[0]: 0.6,
            _SIGNAL_NAMES[1]: 0.5,
        })
        val = ConsensusSignalValidator(min_agreeing=3)
        with patch(_PATCH, return_value=reg):
            r = val.compute()
        assert r.consensus_value == pytest.approx(0.0)

    def test_three_agreeing_value_nonzero(self):
        reg = _make_registry({
            _SIGNAL_NAMES[0]: 0.6,
            _SIGNAL_NAMES[1]: 0.5,
            _SIGNAL_NAMES[2]: 0.4,
        })
        val = ConsensusSignalValidator(min_agreeing=3)
        with patch(_PATCH, return_value=reg):
            r = val.compute()
        assert r.consensus_value != pytest.approx(0.0)
        assert r.consensus_value > 0


class TestConsensusGateSplitSignals:
    """Mixed bullish/bearish signals should not reach consensus."""

    def test_3_bullish_3_bearish_no_consensus(self):
        signals = {
            _SIGNAL_NAMES[0]:  0.6,
            _SIGNAL_NAMES[1]:  0.5,
            _SIGNAL_NAMES[2]:  0.4,
            _SIGNAL_NAMES[3]: -0.6,
            _SIGNAL_NAMES[4]: -0.5,
            _SIGNAL_NAMES[5]: -0.4,
        }
        reg = _make_registry(signals)
        val = ConsensusSignalValidator(min_agreeing=4)   # need 4 agreeing
        with patch(_PATCH, return_value=reg):
            r = val.compute()
        assert not r.consensus_reached
        assert r.consensus_value == pytest.approx(0.0)

    def test_4_bullish_2_bearish_consensus_reached(self):
        signals = {
            _SIGNAL_NAMES[0]:  0.6,
            _SIGNAL_NAMES[1]:  0.5,
            _SIGNAL_NAMES[2]:  0.4,
            _SIGNAL_NAMES[3]:  0.7,
            _SIGNAL_NAMES[4]: -0.6,
            _SIGNAL_NAMES[5]: -0.5,
        }
        reg = _make_registry(signals)
        val = ConsensusSignalValidator(min_agreeing=4)
        with patch(_PATCH, return_value=reg):
            r = val.compute()
        assert r.consensus_reached
        assert r.direction == "bullish"

    def test_direction_threshold_affects_classification(self):
        # Signals with value = 0.1 are neutral at threshold=0.15, bullish at threshold=0.05
        signals = {_SIGNAL_NAMES[i]: 0.1 for i in range(5)}
        reg = _make_registry(signals)

        val_strict = ConsensusSignalValidator(min_agreeing=3, direction_threshold=0.15)
        val_loose  = ConsensusSignalValidator(min_agreeing=3, direction_threshold=0.05)

        with patch(_PATCH, return_value=reg):
            r_strict = val_strict.compute()
        with patch(_PATCH, return_value=reg):
            r_loose  = val_loose.compute()

        assert not r_strict.consensus_reached   # 0.1 < 0.15 → neutral
        assert r_loose.consensus_reached        # 0.1 > 0.05 → bullish


class TestConsensusGateSignalBusIntegration:
    """Signals published to registry are correctly read by validator."""

    def test_published_signals_read_by_validator(self):
        """Full flow: publish 4 bullish signals → consensus_reached."""
        reg = SignalRegistry()

        for i in range(4):
            reg.publish(Signal(
                name=_SIGNAL_NAMES[i], value=0.5,
                confidence=0.8, source_module="test_bus",
            ))

        val = ConsensusSignalValidator(min_agreeing=3)
        with patch(_PATCH, return_value=reg):
            r = val.compute()

        assert r.consensus_reached
        assert r.direction == "bullish"

    def test_insufficient_published_signals(self):
        """2 signals published → consensus not reached."""
        reg = SignalRegistry()

        for i in range(2):
            reg.publish(Signal(
                name=_SIGNAL_NAMES[i], value=0.5,
                confidence=0.8, source_module="test_bus",
            ))

        val = ConsensusSignalValidator(min_agreeing=3)
        with patch(_PATCH, return_value=reg):
            r = val.compute()

        assert not r.consensus_reached
        assert r.consensus_value == pytest.approx(0.0)

    def test_to_signal_value_zero_when_no_consensus(self):
        reg = SignalRegistry()   # empty
        val = ConsensusSignalValidator(min_agreeing=3)
        with patch(_PATCH, return_value=reg):
            snap = val.compute()
            s = val.to_signal(snap)
        assert s.value == pytest.approx(0.0)
        assert not snap.consensus_reached


class TestConsensusGateAgreingSignalsList:
    def test_agreeing_signals_contains_correct_names(self):
        signals = {
            _SIGNAL_NAMES[0]: 0.7,
            _SIGNAL_NAMES[1]: 0.6,
            _SIGNAL_NAMES[2]: 0.5,
        }
        reg = _make_registry(signals)
        val = ConsensusSignalValidator(min_agreeing=3)
        with patch(_PATCH, return_value=reg):
            r = val.compute()
        assert len(r.agreeing_signals) == 3
        for name in signals:
            assert name in r.agreeing_signals

    def test_agreeing_signals_empty_on_no_consensus(self):
        reg = _make_registry({_SIGNAL_NAMES[0]: 0.5})
        val = ConsensusSignalValidator(min_agreeing=3)
        with patch(_PATCH, return_value=reg):
            r = val.compute()
        assert r.agreeing_signals == []
