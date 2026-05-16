"""Tests for shared.signal_types — Signal dataclass (QC-1)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from shared.signal_types import QUALITY_FLAGS, SIGNAL_CUSTOM_PREFIX, Signal


class TestSignalClamp:
    def test_value_clamped_above(self) -> None:
        s = Signal(name="x", value=2.5, confidence=0.5, source_module="m")
        assert s.value == pytest.approx(1.0)

    def test_value_clamped_below(self) -> None:
        s = Signal(name="x", value=-99.0, confidence=0.5, source_module="m")
        assert s.value == pytest.approx(-1.0)

    def test_confidence_clamped_above(self) -> None:
        s = Signal(name="x", value=0.5, confidence=5.0, source_module="m")
        assert s.confidence == pytest.approx(1.0)

    def test_confidence_clamped_below(self) -> None:
        s = Signal(name="x", value=0.5, confidence=-1.0, source_module="m")
        assert s.confidence == pytest.approx(0.0)

    def test_value_within_range_unchanged(self) -> None:
        s = Signal(name="x", value=0.4, confidence=0.7, source_module="m")
        assert s.value == pytest.approx(0.4)
        assert s.confidence == pytest.approx(0.7)


class TestSignalDirection:
    def test_bullish(self) -> None:
        s = Signal(name="x", value=0.5, confidence=0.8, source_module="m")
        assert s.direction == "bullish"

    def test_bearish(self) -> None:
        s = Signal(name="x", value=-0.5, confidence=0.8, source_module="m")
        assert s.direction == "bearish"

    def test_neutral_positive(self) -> None:
        s = Signal(name="x", value=0.1, confidence=0.5, source_module="m")
        assert s.direction == "neutral"

    def test_neutral_negative(self) -> None:
        s = Signal(name="x", value=-0.1, confidence=0.5, source_module="m")
        assert s.direction == "neutral"

    def test_boundary_bullish(self) -> None:
        s = Signal(name="x", value=0.3, confidence=0.5, source_module="m")
        assert s.direction == "neutral"    # exactly 0.3 → not > 0.3

    def test_just_above_bullish_boundary(self) -> None:
        s = Signal(name="x", value=0.31, confidence=0.5, source_module="m")
        assert s.direction == "bullish"


class TestSignalReliable:
    def test_reliable_when_no_ic(self) -> None:
        s = Signal(name="x", value=0.5, confidence=0.8, source_module="m", ic_estimate=None)
        assert s.is_reliable is True

    def test_reliable_when_ok(self) -> None:
        s = Signal(name="x", value=0.5, confidence=0.8, source_module="m",
                   ic_estimate=0.1, quality_flag="ok")
        assert s.is_reliable is True

    def test_not_reliable_when_low_ic(self) -> None:
        s = Signal(name="x", value=0.5, confidence=0.8, source_module="m",
                   ic_estimate=0.01, quality_flag="low_ic")
        assert s.is_reliable is False

    def test_not_reliable_when_stale(self) -> None:
        s = Signal(name="x", value=0.5, confidence=0.8, source_module="m",
                   quality_flag="stale")
        assert s.is_reliable is False


class TestSignalQualityFlagValidation:
    def test_invalid_quality_flag_raises(self) -> None:
        with pytest.raises(ValueError, match="quality_flag"):
            Signal(name="x", value=0.0, confidence=0.5, source_module="m",
                   quality_flag="invalid")  # type: ignore[arg-type]

    def test_all_valid_flags_accepted(self) -> None:
        for flag in QUALITY_FLAGS:
            s = Signal(name="x", value=0.0, confidence=0.5, source_module="m",
                       quality_flag=flag)
            assert s.quality_flag == flag


class TestSignalDefaults:
    def test_default_timestamp_is_utc(self) -> None:
        before = datetime.now(UTC)
        s = Signal(name="x", value=0.0, confidence=0.5, source_module="m")
        after = datetime.now(UTC)
        assert before <= s.timestamp <= after

    def test_default_quality_flag_ok(self) -> None:
        s = Signal(name="x", value=0.0, confidence=0.5, source_module="m")
        assert s.quality_flag == "ok"

    def test_default_ic_none(self) -> None:
        s = Signal(name="x", value=0.0, confidence=0.5, source_module="m")
        assert s.ic_estimate is None

    def test_default_regime_none(self) -> None:
        s = Signal(name="x", value=0.0, confidence=0.5, source_module="m")
        assert s.regime_label is None


class TestSignalConstants:
    def test_custom_prefix(self) -> None:
        assert SIGNAL_CUSTOM_PREFIX == "custom."

    def test_all_quality_flags_known(self) -> None:
        assert set(QUALITY_FLAGS) == {"ok", "low_ic", "insufficient_data", "stale"}

    def test_signal_is_frozen(self) -> None:
        s = Signal(name="x", value=0.0, confidence=0.5, source_module="m")
        with pytest.raises((AttributeError, TypeError)):
            s.value = 0.9  # type: ignore[misc]
