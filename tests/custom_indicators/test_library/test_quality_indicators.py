"""Tests for pre-built quality indicators #7-10 (QC DoD criteria)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_indicators.library.consensus_signal_validator import ConsensusSignalValidator
from custom_indicators.library.regime_signal_filter import RegimeSignalFilter
from custom_indicators.library.signal_confidence_tracker import (
    SignalConfidenceTracker,
)
from custom_indicators.library.volatility_adjusted_signal import VolatilityAdjustedSignal
from shared.alpha_decay_monitor import AlphaDecayMonitor
from shared.signal_registry import SignalRegistry
from shared.signal_types import Signal


def _reg(**signals: float) -> SignalRegistry:
    reg = SignalRegistry()
    for name, val in signals.items():
        reg.publish(Signal(name=name, value=val, confidence=0.8, source_module="test"))
    return reg


def _monitor_with_ic(ic_map: dict[str, float]) -> AlphaDecayMonitor:
    """Mock AlphaDecayMonitor returning specific ICs."""
    m = MagicMock(spec=AlphaDecayMonitor)
    def _check(sig_name: str):
        ic = ic_map.get(sig_name)
        if ic is None:
            return None, "insufficient_data"
        flag = "ok" if ic >= 0.05 else "low_ic"
        return ic, flag
    m.check_decay.side_effect = _check
    return m


# ── #7 SignalConfidenceTracker ────────────────────────────────────────────

class TestSignalConfidenceTracker:
    def test_all_insufficient_data_returns_full_score(self) -> None:
        monitor = _monitor_with_ic({})    # no IC data → benefit of doubt
        tracker = SignalConfidenceTracker(monitor)
        snap = tracker.compute()
        assert snap.overall_score == pytest.approx(1.0)

    def test_all_ok_ic_returns_high_score(self) -> None:
        ics = {n: 0.10 for n in [
            "technical_composite", "macro_conviction", "labour_regime_signal",
            "sentiment_composite", "valuation_signal", "economic_surprise_index", "vix_signal",
        ]}
        monitor = _monitor_with_ic(ics)
        tracker = SignalConfidenceTracker(monitor)
        snap = tracker.compute()
        assert snap.overall_score > 0.7        # DoD: > 0.7 if all IC ok
        assert snap.signals_ok == 7
        assert snap.signals_low_ic == 0

    def test_three_degraded_reduces_score(self) -> None:
        signals = [
            "technical_composite", "macro_conviction", "labour_regime_signal",
            "sentiment_composite", "valuation_signal", "economic_surprise_index", "vix_signal",
        ]
        ics = {n: (0.001 if i < 3 else 0.10) for i, n in enumerate(signals)}
        monitor = _monitor_with_ic(ics)
        tracker = SignalConfidenceTracker(monitor)
        snap = tracker.compute()
        assert snap.overall_score < 0.5       # DoD: < 0.5 if 3+ degraded
        assert snap.signals_low_ic >= 3

    def test_to_signal_name(self) -> None:
        monitor = _monitor_with_ic({})
        tracker = SignalConfidenceTracker(monitor)
        s = tracker.to_signal(tracker.compute())
        assert s.name == "custom.signal_confidence_tracker"

    def test_worst_signal_identified(self) -> None:
        ics = {"technical_composite": 0.01, "macro_conviction": 0.08}
        monitor = _monitor_with_ic(ics)
        tracker = SignalConfidenceTracker(monitor)
        snap = tracker.compute()
        assert snap.worst_signal == "technical_composite"
        assert snap.worst_ic == pytest.approx(0.01)


# ── #8 RegimeSignalFilter ─────────────────────────────────────────────────

class TestRegimeSignalFilter:
    def test_high_ic_all_included(self) -> None:
        reg = _reg(
            technical_composite=0.5, macro_conviction=0.4,
            labour_regime_signal=0.3, sentiment_composite=0.6,
            valuation_signal=0.2, economic_surprise_index=0.1,
        )
        monitor = _monitor_with_ic({
            "technical_composite": 0.10, "macro_conviction": 0.08,
            "labour_regime_signal": 0.07, "sentiment_composite": 0.09,
            "valuation_signal": 0.06, "economic_surprise_index": 0.05,
        })
        flt = RegimeSignalFilter(decay_monitor=monitor)
        with patch("custom_indicators.library.regime_signal_filter.get_signal_registry",
                   return_value=reg):
            r = flt.compute("bull")
        assert r.n_signals_used == 6
        assert r.n_signals_filtered == 0     # DoD: excludes IC < 0.03

    def test_low_ic_signals_excluded(self) -> None:
        reg = _reg(technical_composite=0.5, macro_conviction=0.4)
        monitor = _monitor_with_ic({
            "technical_composite": 0.001,   # below threshold → filtered
            "macro_conviction":    0.08,    # above threshold → kept
        })
        flt = RegimeSignalFilter(decay_monitor=monitor, ic_regime_threshold=0.03)
        with patch("custom_indicators.library.regime_signal_filter.get_signal_registry",
                   return_value=reg):
            r = flt.compute("bear")
        assert r.n_signals_filtered >= 1    # DoD: excluded IC < 0.03

    def test_all_below_threshold_returns_zero(self) -> None:
        reg = _reg(technical_composite=0.5)
        monitor = _monitor_with_ic({"technical_composite": 0.001})
        flt = RegimeSignalFilter(decay_monitor=monitor, ic_regime_threshold=0.03)
        with patch("custom_indicators.library.regime_signal_filter.get_signal_registry",
                   return_value=reg):
            r = flt.compute("bear")
        assert r.filtered_composite == pytest.approx(0.0)  # DoD edge case

    def test_composite_in_range(self) -> None:
        reg = _reg(technical_composite=0.9, macro_conviction=0.8)
        monitor = _monitor_with_ic({"technical_composite": 0.1, "macro_conviction": 0.1})
        flt = RegimeSignalFilter(decay_monitor=monitor)
        with patch("custom_indicators.library.regime_signal_filter.get_signal_registry",
                   return_value=reg):
            r = flt.compute("bull")
        assert -1.0 <= r.filtered_composite <= 1.0

    def test_to_signal_name(self) -> None:
        reg = _reg()
        monitor = _monitor_with_ic({})
        flt = RegimeSignalFilter(decay_monitor=monitor)
        with patch("custom_indicators.library.regime_signal_filter.get_signal_registry",
                   return_value=reg):
            s = flt.to_signal(flt.compute())
        assert s.name == "custom.regime_signal_filter"


# ── #9 ConsensusSignalValidator ───────────────────────────────────────────

class TestConsensusSignalValidator:
    def test_consensus_not_reached_returns_zero(self) -> None:
        reg = _reg(technical_composite=0.5, macro_conviction=-0.5)  # split
        val = ConsensusSignalValidator(min_agreeing=3)
        with patch("custom_indicators.library.consensus_signal_validator.get_signal_registry",
                   return_value=reg):
            r = val.compute()
        assert r.consensus_value == pytest.approx(0.0)   # DoD
        assert r.consensus_reached is False

    def test_bullish_consensus(self) -> None:
        reg = _reg(
            technical_composite=0.5, macro_conviction=0.4,
            labour_regime_signal=0.3, sentiment_composite=0.6,
        )
        val = ConsensusSignalValidator(min_agreeing=3, direction_threshold=0.15)
        with patch("custom_indicators.library.consensus_signal_validator.get_signal_registry",
                   return_value=reg):
            r = val.compute()
        assert r.consensus_reached is True     # DoD: bullish if ≥ 3 > 0.15
        assert r.direction == "bullish"
        assert r.consensus_value > 0

    def test_bearish_consensus(self) -> None:
        reg = _reg(
            technical_composite=-0.5, macro_conviction=-0.4,
            labour_regime_signal=-0.3, sentiment_composite=-0.6,
        )
        val = ConsensusSignalValidator(min_agreeing=3)
        with patch("custom_indicators.library.consensus_signal_validator.get_signal_registry",
                   return_value=reg):
            r = val.compute()
        assert r.direction == "bearish"
        assert r.consensus_value < 0

    def test_to_signal_name(self) -> None:
        reg = _reg()
        val = ConsensusSignalValidator()
        with patch("custom_indicators.library.consensus_signal_validator.get_signal_registry",
                   return_value=reg):
            s = val.to_signal(val.compute())
        assert s.name == "custom.consensus_signal_validator"


# ── #10 VolatilityAdjustedSignal ──────────────────────────────────────────

class TestVolatilityAdjustedSignal:
    def test_stress_vix_scale_040(self) -> None:
        # vix_signal = -1 → vix_level = 40 → scale 0.40
        reg = _reg(vix_signal=-1.0, composite_signal_v3=0.8)
        vol_ind = VolatilityAdjustedSignal()
        with patch("custom_indicators.library.volatility_adjusted_signal.get_signal_registry",
                   return_value=reg):
            r = vol_ind.compute()
        assert r.scale_factor == pytest.approx(0.40)   # DoD: scale=0.40 if vix > 35
        assert r.vix_regime == "stress"

    def test_low_vix_scale_115(self) -> None:
        # vix_signal = +1 → vix_level = 12 → scale 1.15
        reg = _reg(vix_signal=1.0, composite_signal_v3=0.5)
        vol_ind = VolatilityAdjustedSignal()
        with patch("custom_indicators.library.volatility_adjusted_signal.get_signal_registry",
                   return_value=reg):
            r = vol_ind.compute()
        assert r.scale_factor == pytest.approx(1.15)   # DoD: scale=1.15 if vix < 16
        assert r.vix_regime == "low"

    def test_adjusted_in_range(self) -> None:
        reg = _reg(vix_signal=0.0, composite_signal_v3=0.9)
        vol_ind = VolatilityAdjustedSignal()
        with patch("custom_indicators.library.volatility_adjusted_signal.get_signal_registry",
                   return_value=reg):
            r = vol_ind.compute()
        assert -1.0 <= r.adjusted_composite <= 1.0

    def test_to_signal_name(self) -> None:
        reg = _reg()
        vol_ind = VolatilityAdjustedSignal()
        with patch("custom_indicators.library.volatility_adjusted_signal.get_signal_registry",
                   return_value=reg):
            s = vol_ind.to_signal(vol_ind.compute())
        assert s.name == "custom.volatility_adjusted_signal"
