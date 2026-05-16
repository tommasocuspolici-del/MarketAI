"""Tests for SignalConfidenceTracker (#7 QC) — dedicated file.

Complements test_quality_indicators.py with extended edge-case coverage.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_indicators.library.signal_confidence_tracker import (
    TRACKED_SIGNALS,
    SignalConfidenceTracker,
    SignalQualitySnapshot,
)
from shared.alpha_decay_monitor import AlphaDecayMonitor, IC_MIN_THRESHOLD
from shared.signal_types import Signal


def _monitor(ic_map: dict[str, float | None]) -> AlphaDecayMonitor:
    m = MagicMock(spec=AlphaDecayMonitor)
    def _check(name: str):
        ic = ic_map.get(name)
        if ic is None:
            return None, "insufficient_data"
        flag = "ok" if ic >= IC_MIN_THRESHOLD * 2.5 else "low_ic"
        return ic, flag
    m.check_decay.side_effect = _check
    return m


class TestSignalConfidenceTrackerCompute:
    def test_all_signals_tracked(self):
        called: list[str] = []
        m = MagicMock(spec=AlphaDecayMonitor)
        m.check_decay.side_effect = lambda n: (called.append(n), (None, "insufficient_data"))[1]
        SignalConfidenceTracker(m).compute()
        assert set(called) == set(TRACKED_SIGNALS)

    def test_score_range_always_01(self):
        for ic_val in [0.0, 0.001, 0.02, 0.05, 0.10, 0.50]:
            ics = {n: ic_val for n in TRACKED_SIGNALS}
            mon = _monitor(ics)
            snap = SignalConfidenceTracker(mon).compute()
            assert 0.0 <= snap.overall_score <= 1.0, f"score out of range for ic={ic_val}"

    def test_single_low_ic_reduces_score(self):
        ics = {n: 0.10 for n in TRACKED_SIGNALS}
        ics["vix_signal"] = 0.001    # one bad signal
        snap = SignalConfidenceTracker(_monitor(ics)).compute()
        # score should be below fully-healthy baseline
        ics_all_ok = {n: 0.10 for n in TRACKED_SIGNALS}
        snap_ok = SignalConfidenceTracker(_monitor(ics_all_ok)).compute()
        assert snap.overall_score < snap_ok.overall_score

    def test_signals_ok_count(self):
        ics = {n: 0.10 for n in TRACKED_SIGNALS}
        snap = SignalConfidenceTracker(_monitor(ics)).compute()
        assert snap.signals_ok == len(TRACKED_SIGNALS)
        assert snap.signals_low_ic == 0
        assert snap.signals_degraded == 0

    def test_signals_low_ic_count(self):
        ics = {n: 0.001 for n in TRACKED_SIGNALS}
        snap = SignalConfidenceTracker(_monitor(ics)).compute()
        assert snap.signals_low_ic == len(TRACKED_SIGNALS)

    def test_worst_signal_none_when_no_ic_data(self):
        snap = SignalConfidenceTracker(_monitor({})).compute()
        assert snap.worst_signal is None
        assert snap.worst_ic is None

    def test_worst_ic_is_minimum(self):
        ics = {"technical_composite": 0.03, "macro_conviction": 0.01,
               "sentiment_composite": 0.05}
        snap = SignalConfidenceTracker(_monitor(ics)).compute()
        assert snap.worst_ic == pytest.approx(0.01)
        assert snap.worst_signal == "macro_conviction"

    def test_single_signal_with_ic(self):
        snap = SignalConfidenceTracker(_monitor({"technical_composite": 0.08})).compute()
        assert snap.worst_ic == pytest.approx(0.08)

    def test_snapshot_is_dataclass(self):
        snap = SignalConfidenceTracker(_monitor({})).compute()
        assert isinstance(snap, SignalQualitySnapshot)


class TestSignalConfidenceTrackerToSignal:
    def test_signal_name(self):
        mon = _monitor({})
        tracker = SignalConfidenceTracker(mon)
        s = tracker.to_signal(tracker.compute())
        assert s.name == "custom.signal_confidence_tracker"

    def test_signal_value_in_range(self):
        for ic_val in [0.0, 0.001, 0.05, 0.10]:
            ics = {n: ic_val for n in TRACKED_SIGNALS}
            tracker = SignalConfidenceTracker(_monitor(ics))
            s = tracker.to_signal(tracker.compute())
            assert -1.0 <= s.value <= 1.0, f"value={s.value} out of range for ic={ic_val}"

    def test_signal_confidence_equals_overall_score(self):
        ics = {n: 0.10 for n in TRACKED_SIGNALS}
        tracker = SignalConfidenceTracker(_monitor(ics))
        snap = tracker.compute()
        s = tracker.to_signal(snap)
        assert s.confidence == pytest.approx(snap.overall_score)

    def test_signal_is_frozen(self):
        mon = _monitor({})
        tracker = SignalConfidenceTracker(mon)
        s = tracker.to_signal(tracker.compute())
        with pytest.raises(Exception):
            s.value = 0.0  # type: ignore[misc]

    def test_metadata_keys_present(self):
        mon = _monitor({})
        tracker = SignalConfidenceTracker(mon)
        s = tracker.to_signal(tracker.compute())
        for key in ("signals_ok", "signals_low_ic", "signals_degraded",
                    "worst_signal", "worst_ic"):
            assert key in s.metadata

    def test_full_score_maps_to_positive_value(self):
        # overall_score=1.0 → value = 1.0*2-1 = 1.0
        mon = _monitor({})    # no IC → full score
        tracker = SignalConfidenceTracker(mon)
        snap = tracker.compute()
        s = tracker.to_signal(snap)
        assert snap.overall_score == pytest.approx(1.0)
        assert s.value == pytest.approx(1.0)
