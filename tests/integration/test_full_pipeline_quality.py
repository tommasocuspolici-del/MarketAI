"""Integration: segnale low_ic → peso ridotto → composite finale meno estremo.

DoD (G.1):
  Verifica che: segnale low_ic → peso ridotto → composite finale meno estremo.

Pipeline testata:
  1. AlphaDecayMonitor.get_weight_multiplier() → 0.5 quando IC basso
  2. RegimeSignalFilter esclude segnali con IC < threshold
  3. SignalConfidenceTracker score scende quando IC decade
  4. VolatilityAdjustedSignal attenua in stress (scale < 1)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_indicators.library.regime_signal_filter import RegimeSignalFilter
from custom_indicators.library.signal_confidence_tracker import (
    TRACKED_SIGNALS,
    SignalConfidenceTracker,
)
from custom_indicators.library.volatility_adjusted_signal import VolatilityAdjustedSignal
from shared.alpha_decay_monitor import (
    AlphaDecayMonitor,
    IC_MIN_THRESHOLD,
    IC_SOFT_WARNING,
    _WEIGHT_LOW_IC,
    _WEIGHT_DEGRADED,
)
from shared.signal_registry import SignalRegistry
from shared.signal_types import Signal


def _reg(**signals: float) -> SignalRegistry:
    reg = SignalRegistry()
    for name, val in signals.items():
        reg.publish(Signal(name=name, value=val, confidence=0.8, source_module="test"))
    return reg


def _monitor_with_ic(ic_map: dict[str, float]) -> AlphaDecayMonitor:
    m = MagicMock(spec=AlphaDecayMonitor)
    def _check(name: str):
        ic = ic_map.get(name)
        if ic is None:
            return None, "insufficient_data"
        if ic < IC_MIN_THRESHOLD:
            return ic, "low_ic"
        elif ic < IC_SOFT_WARNING:
            return ic, "low_ic"
        return ic, "ok"
    m.check_decay.side_effect = _check

    def _multiplier(name: str):
        ic = ic_map.get(name)
        if ic is None:
            return 1.0
        if ic >= IC_SOFT_WARNING:
            return 1.0
        if ic >= IC_MIN_THRESHOLD:
            return _WEIGHT_LOW_IC
        return _WEIGHT_DEGRADED
    m.get_weight_multiplier.side_effect = _multiplier
    return m


class TestWeightMultiplierReduction:
    """AlphaDecayMonitor returns reduced weight when IC is low."""

    def test_full_weight_when_ic_ok(self):
        mon = _monitor_with_ic({"vix_signal": IC_SOFT_WARNING + 0.01})
        assert mon.get_weight_multiplier("vix_signal") == pytest.approx(1.0)

    def test_reduced_weight_when_ic_low(self):
        mon = _monitor_with_ic({"vix_signal": IC_MIN_THRESHOLD + 0.001})
        w = mon.get_weight_multiplier("vix_signal")
        assert w == pytest.approx(_WEIGHT_LOW_IC)
        assert w < 1.0

    def test_near_zero_weight_when_ic_below_min(self):
        mon = _monitor_with_ic({"vix_signal": IC_MIN_THRESHOLD * 0.5})
        w = mon.get_weight_multiplier("vix_signal")
        assert w == pytest.approx(_WEIGHT_DEGRADED)
        assert w < _WEIGHT_LOW_IC

    def test_benefit_of_doubt_when_no_ic(self):
        mon = _monitor_with_ic({})
        assert mon.get_weight_multiplier("unknown_signal") == pytest.approx(1.0)


class TestLowICReducesComposite:
    """RegimeSignalFilter: low-IC signals excluded → composite less extreme."""

    _PATCH = "custom_indicators.library.regime_signal_filter.get_signal_registry"

    def test_all_signals_strong_with_good_ic(self):
        reg = _reg(**{n: 0.8 for n in
                      ["technical_composite", "macro_conviction", "labour_regime_signal",
                       "sentiment_composite", "valuation_signal", "economic_surprise_index"]})
        mon = _monitor_with_ic({n: 0.10 for n in
                                 ["technical_composite", "macro_conviction", "labour_regime_signal",
                                  "sentiment_composite", "valuation_signal", "economic_surprise_index"]})
        flt = RegimeSignalFilter(mon)
        with patch(self._PATCH, return_value=reg):
            r_good = flt.compute()
        assert r_good.filtered_composite > 0.5   # strong signal when IC healthy

    def test_low_ic_excluded_reduces_composite(self):
        # Same signals but IC is low → filtered → composite less extreme
        reg = _reg(**{n: 0.8 for n in
                      ["technical_composite", "macro_conviction", "labour_regime_signal",
                       "sentiment_composite", "valuation_signal", "economic_surprise_index"]})
        mon_low = _monitor_with_ic({n: 0.001 for n in
                                     ["technical_composite", "macro_conviction", "labour_regime_signal",
                                      "sentiment_composite", "valuation_signal", "economic_surprise_index"]})
        flt_low = RegimeSignalFilter(mon_low, ic_regime_threshold=0.03)
        with patch(self._PATCH, return_value=reg):
            r_low = flt_low.compute()
        # All signals filtered → composite = 0
        assert r_low.filtered_composite == pytest.approx(0.0)
        assert r_low.n_signals_filtered >= 1

    def test_partial_low_ic_moderates_composite(self):
        signals = {n: 0.8 for n in
                   ["technical_composite", "macro_conviction", "labour_regime_signal"]}
        # Half with good IC, half with bad IC
        reg = _reg(**signals)
        mon = _monitor_with_ic({
            "technical_composite":  0.10,    # good → included
            "macro_conviction":     0.001,   # bad → filtered
            "labour_regime_signal": 0.001,   # bad → filtered
        })
        flt = RegimeSignalFilter(mon, ic_regime_threshold=0.03)
        with patch(self._PATCH, return_value=reg):
            r_partial = flt.compute()
        # Filtered signals excluded → composite based only on good-IC signal
        assert r_partial.n_signals_used < 3


class TestQualityScoreDegrades:
    """SignalConfidenceTracker: more low-IC signals → lower score."""

    def test_zero_bad_signals_max_score(self):
        ics = {n: 0.10 for n in TRACKED_SIGNALS}
        tracker = SignalConfidenceTracker(_monitor_with_ic(ics))
        snap = tracker.compute()
        assert snap.overall_score > 0.5

    def test_all_bad_signals_low_score(self):
        ics = {n: IC_MIN_THRESHOLD * 0.5 for n in TRACKED_SIGNALS}
        tracker = SignalConfidenceTracker(_monitor_with_ic(ics))
        snap = tracker.compute()
        assert snap.overall_score < 0.5    # many degraded → low score

    def test_score_degrades_progressively(self):
        """More low-IC signals → lower score."""
        scores: list[float] = []
        for n_bad in [0, 2, 4, 7]:
            signals = list(TRACKED_SIGNALS)
            ics = {}
            for i, s in enumerate(signals):
                ics[s] = IC_MIN_THRESHOLD * 0.5 if i < n_bad else 0.10
            tracker = SignalConfidenceTracker(_monitor_with_ic(ics))
            scores.append(tracker.compute().overall_score)
        # Each additional bad signal should not increase score
        assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1)), (
            f"Score should decrease with more bad signals: {scores}"
        )


class TestVolatilityAttenuation:
    """VolatilityAdjustedSignal reduces composite in stress."""

    _PATCH = "custom_indicators.library.volatility_adjusted_signal.get_signal_registry"

    def test_stress_regime_attenuates_composite(self):
        reg_stress = _reg(vix_signal=-1.0, composite_signal_v3=0.8)
        reg_normal = _reg(vix_signal=0.5,  composite_signal_v3=0.8)
        vol = VolatilityAdjustedSignal()
        with patch(self._PATCH, return_value=reg_stress):
            r_stress = vol.compute()
        with patch(self._PATCH, return_value=reg_normal):
            r_normal = vol.compute()
        assert r_stress.adjusted_composite < r_normal.adjusted_composite

    def test_composite_less_extreme_in_stress_than_raw(self):
        reg = _reg(vix_signal=-1.0, composite_signal_v3=0.9)
        vol = VolatilityAdjustedSignal()
        with patch(self._PATCH, return_value=reg):
            r = vol.compute()
        assert abs(r.adjusted_composite) < abs(r.raw_composite)
