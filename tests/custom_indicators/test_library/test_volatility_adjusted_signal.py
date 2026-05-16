"""Tests for VolatilityAdjustedSignal (#10 QC) — dedicated file."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from custom_indicators.library.volatility_adjusted_signal import (
    VolatilityAdjustedSignal,
    VolAdjustedResult,
    _VIX_SCALE_TABLE,
)
from shared.signal_registry import SignalRegistry
from shared.signal_types import Signal


def _reg(**signals: float) -> SignalRegistry:
    reg = SignalRegistry()
    for name, val in signals.items():
        reg.publish(Signal(name=name, value=val, confidence=0.8, source_module="test"))
    return reg


_PATCH = "custom_indicators.library.volatility_adjusted_signal.get_signal_registry"

# VIX-level formula: vix_level = 26.0 - vix_signal * 14.0
# vix_signal → vix_level:
#   +1.0  → 12.0  (low vol)
#   +0.0  → 26.0  (high vol)
#   -0.5  → 33.0  (high vol)
#   -1.0  → 40.0  (stress)


class TestVIXScaleFactors:
    """DoD: each VIX regime produces correct scale factor."""

    def test_low_vix_scale_115(self):
        # vix_signal=1.0 → vix_level=12 → scale=1.15
        reg = _reg(vix_signal=1.0, composite_signal_v3=0.5)
        with patch(_PATCH, return_value=reg):
            r = VolatilityAdjustedSignal().compute()
        assert r.scale_factor == pytest.approx(1.15)
        assert r.vix_regime == "low"

    def test_normal_vix_scale_100(self):
        # vix_signal=0.0 → vix_level=26 → scale=1.00 (high, not normal)
        # For normal: need 16 ≤ vix_level < 25 → vix_signal > 0.07
        reg = _reg(vix_signal=0.5, composite_signal_v3=0.5)   # vix=19 → normal
        with patch(_PATCH, return_value=reg):
            r = VolatilityAdjustedSignal().compute()
        assert r.scale_factor == pytest.approx(1.00)
        assert r.vix_regime == "normal"

    def test_high_vix_scale_070(self):
        # vix_signal=-0.3 → vix_level=30.2 → scale=0.70
        reg = _reg(vix_signal=-0.3, composite_signal_v3=0.5)
        with patch(_PATCH, return_value=reg):
            r = VolatilityAdjustedSignal().compute()
        assert r.scale_factor == pytest.approx(0.70)
        assert r.vix_regime == "high"

    def test_stress_vix_scale_040(self):
        # vix_signal=-1.0 → vix_level=40 → scale=0.40
        reg = _reg(vix_signal=-1.0, composite_signal_v3=0.8)
        with patch(_PATCH, return_value=reg):
            r = VolatilityAdjustedSignal().compute()
        assert r.scale_factor == pytest.approx(0.40)
        assert r.vix_regime == "stress"

    def test_scale_table_is_contiguous(self):
        # Every VIX level from 0 to 60 falls in exactly one bucket
        for vix_level in range(0, 60):
            matches = [(lo, hi, factor, label)
                       for lo, hi, factor, label in _VIX_SCALE_TABLE
                       if lo <= vix_level < hi]
            assert len(matches) == 1, f"vix_level={vix_level} matched {len(matches)} buckets"


class TestVolatilityAdjustedCompute:
    def test_adjusted_composite_in_range(self):
        for vix_sig in [-1.0, -0.5, 0.0, 0.5, 1.0]:
            for raw_sig in [-1.0, -0.5, 0.0, 0.5, 1.0]:
                reg = _reg(vix_signal=vix_sig, composite_signal_v3=raw_sig)
                with patch(_PATCH, return_value=reg):
                    r = VolatilityAdjustedSignal().compute()
                assert -1.0 <= r.adjusted_composite <= 1.0, (
                    f"Out of range: vix={vix_sig}, raw={raw_sig}, adj={r.adjusted_composite}"
                )

    def test_stress_attenuates_positive_signal(self):
        reg = _reg(vix_signal=-1.0, composite_signal_v3=0.8)
        with patch(_PATCH, return_value=reg):
            r = VolatilityAdjustedSignal().compute()
        # Stress scale=0.40, raw=0.8 → adjusted=0.32
        assert r.adjusted_composite == pytest.approx(0.8 * 0.40, abs=0.001)

    def test_low_vol_amplifies_signal(self):
        reg = _reg(vix_signal=1.0, composite_signal_v3=0.5)
        with patch(_PATCH, return_value=reg):
            r = VolatilityAdjustedSignal().compute()
        # Low scale=1.15, raw=0.5 → adjusted=0.575
        assert r.adjusted_composite == pytest.approx(0.5 * 1.15, abs=0.001)

    def test_clipping_prevents_overflow(self):
        # Scale 1.15 × 0.95 = 1.0925 → clipped to 1.0
        reg = _reg(vix_signal=1.0, composite_signal_v3=0.95)
        with patch(_PATCH, return_value=reg):
            r = VolatilityAdjustedSignal().compute()
        assert r.adjusted_composite <= 1.0

    def test_raw_composite_stored(self):
        reg = _reg(vix_signal=0.5, composite_signal_v3=0.4)
        with patch(_PATCH, return_value=reg):
            r = VolatilityAdjustedSignal().compute()
        assert r.raw_composite == pytest.approx(0.4, abs=0.001)

    def test_default_vix_zero_when_missing(self):
        reg = _reg(composite_signal_v3=0.5)    # no vix_signal
        with patch(_PATCH, return_value=reg):
            r = VolatilityAdjustedSignal().compute()
        # vix_signal=0.0 → vix_level=26 → high regime scale=0.70
        assert r.scale_factor == pytest.approx(0.70)

    def test_result_is_dataclass(self):
        reg = _reg()
        with patch(_PATCH, return_value=reg):
            r = VolatilityAdjustedSignal().compute()
        assert isinstance(r, VolAdjustedResult)


class TestVolatilityAdjustedToSignal:
    def test_signal_name(self):
        reg = _reg()
        vol = VolatilityAdjustedSignal()
        with patch(_PATCH, return_value=reg):
            s = vol.to_signal(vol.compute())
        assert s.name == "custom.volatility_adjusted_signal"

    def test_signal_value_equals_adjusted_composite(self):
        reg = _reg(vix_signal=-1.0, composite_signal_v3=0.8)
        vol = VolatilityAdjustedSignal()
        with patch(_PATCH, return_value=reg):
            snap = vol.compute()
            s = vol.to_signal(snap)
        assert s.value == pytest.approx(snap.adjusted_composite)

    def test_confidence_in_range(self):
        for vix_sig in [-1.0, 0.0, 1.0]:
            reg = _reg(vix_signal=vix_sig, composite_signal_v3=0.5)
            vol = VolatilityAdjustedSignal()
            with patch(_PATCH, return_value=reg):
                snap = vol.compute()
                s = vol.to_signal(snap)
            assert 0.0 <= s.confidence <= 1.0

    def test_metadata_has_key_fields(self):
        reg = _reg()
        vol = VolatilityAdjustedSignal()
        with patch(_PATCH, return_value=reg):
            s = vol.to_signal(vol.compute())
        assert "raw_composite" in s.metadata
        assert "vix_level" in s.metadata
        assert "scale_factor" in s.metadata
        assert "vix_regime" in s.metadata

    def test_signal_is_frozen(self):
        reg = _reg()
        vol = VolatilityAdjustedSignal()
        with patch(_PATCH, return_value=reg):
            s = vol.to_signal(vol.compute())
        with pytest.raises(Exception):
            s.value = 0.0  # type: ignore[misc]
