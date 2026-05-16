"""Tests for RegimeSignalFilter (#8 QC) — dedicated file."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_indicators.library.regime_signal_filter import (
    RegimeSignalFilter,
    RegimeFilteredSignal,
    _CORE_SIGNALS,
)
from shared.alpha_decay_monitor import AlphaDecayMonitor
from shared.signal_registry import SignalRegistry
from shared.signal_types import Signal


def _reg(**signals: float) -> SignalRegistry:
    reg = SignalRegistry()
    for name, val in signals.items():
        reg.publish(Signal(name=name, value=val, confidence=0.8, source_module="test"))
    return reg


def _monitor(ic_map: dict[str, float]) -> AlphaDecayMonitor:
    m = MagicMock(spec=AlphaDecayMonitor)
    def _check(name: str):
        ic = ic_map.get(name)
        if ic is None:
            return None, "insufficient_data"
        flag = "ok" if ic >= 0.05 else "low_ic"
        return ic, flag
    m.check_decay.side_effect = _check
    return m


_PATCH = "custom_indicators.library.regime_signal_filter.get_signal_registry"


class TestRegimeSignalFilterCompute:
    def test_empty_registry_returns_zero(self):
        flt = RegimeSignalFilter(_monitor({}))
        with patch(_PATCH, return_value=_reg()):
            r = flt.compute()
        assert r.filtered_composite == pytest.approx(0.0)
        assert r.n_signals_used == 0

    def test_filtered_composite_in_range(self):
        reg = _reg(**{n: 0.9 for n in _CORE_SIGNALS})
        mon = _monitor({n: 0.10 for n in _CORE_SIGNALS})
        flt = RegimeSignalFilter(mon)
        with patch(_PATCH, return_value=reg):
            r = flt.compute()
        assert -1.0 <= r.filtered_composite <= 1.0

    def test_negative_signals_produce_negative_composite(self):
        reg = _reg(**{n: -0.8 for n in _CORE_SIGNALS})
        mon = _monitor({n: 0.10 for n in _CORE_SIGNALS})
        flt = RegimeSignalFilter(mon)
        with patch(_PATCH, return_value=reg):
            r = flt.compute()
        assert r.filtered_composite < 0

    def test_custom_threshold_filters_more(self):
        reg = _reg(technical_composite=0.5, macro_conviction=0.4)
        mon = _monitor({"technical_composite": 0.04, "macro_conviction": 0.04})
        flt_strict = RegimeSignalFilter(mon, ic_regime_threshold=0.05)
        flt_loose  = RegimeSignalFilter(mon, ic_regime_threshold=0.03)
        with patch(_PATCH, return_value=reg):
            r_strict = flt_strict.compute()
        with patch(_PATCH, return_value=reg):
            r_loose  = flt_loose.compute()
        # Strict threshold filters more signals
        assert r_strict.n_signals_used <= r_loose.n_signals_used

    def test_signal_details_keys_are_used_signals(self):
        reg = _reg(technical_composite=0.5, macro_conviction=0.4)
        mon = _monitor({"technical_composite": 0.10, "macro_conviction": 0.08})
        flt = RegimeSignalFilter(mon)
        with patch(_PATCH, return_value=reg):
            r = flt.compute()
        assert "technical_composite" in r.signal_details
        assert "macro_conviction" in r.signal_details

    def test_n_signals_filtered_plus_used_leq_core(self):
        reg = _reg(**{n: 0.5 for n in _CORE_SIGNALS})
        mon = _monitor({n: 0.10 for n in _CORE_SIGNALS})
        flt = RegimeSignalFilter(mon)
        with patch(_PATCH, return_value=reg):
            r = flt.compute()
        assert r.n_signals_used + r.n_signals_filtered <= len(_CORE_SIGNALS)

    def test_benefit_of_doubt_when_ic_none(self):
        # Signal with no IC data should get benefit of doubt (ic=0.05 default)
        reg = _reg(technical_composite=0.5)
        mon = _monitor({})    # no IC → benefit of doubt = 0.05 ≥ threshold 0.03
        flt = RegimeSignalFilter(mon, ic_regime_threshold=0.03)
        with patch(_PATCH, return_value=reg):
            r = flt.compute()
        assert r.n_signals_used >= 1


class TestRegimeSignalFilterToSignal:
    def test_signal_name(self):
        flt = RegimeSignalFilter(_monitor({}))
        with patch(_PATCH, return_value=_reg()):
            s = flt.to_signal(flt.compute())
        assert s.name == "custom.regime_signal_filter"

    def test_confidence_zero_when_no_signals(self):
        flt = RegimeSignalFilter(_monitor({}))
        with patch(_PATCH, return_value=_reg()):
            snap = flt.compute()
            s = flt.to_signal(snap)
        assert snap.n_signals_used == 0
        assert s.confidence == pytest.approx(0.0)

    def test_confidence_positive_when_signals_used(self):
        reg = _reg(**{n: 0.5 for n in _CORE_SIGNALS})
        mon = _monitor({n: 0.10 for n in _CORE_SIGNALS})
        flt = RegimeSignalFilter(mon)
        with patch(_PATCH, return_value=reg):
            snap = flt.compute()
            s = flt.to_signal(snap)
        assert s.confidence > 0.0

    def test_metadata_has_n_used_and_n_filtered(self):
        flt = RegimeSignalFilter(_monitor({}))
        with patch(_PATCH, return_value=_reg()):
            s = flt.to_signal(flt.compute())
        assert "n_used" in s.metadata
        assert "n_filtered" in s.metadata
        assert "details" in s.metadata

    def test_signal_value_equals_filtered_composite(self):
        reg = _reg(technical_composite=0.6, macro_conviction=0.4)
        mon = _monitor({"technical_composite": 0.10, "macro_conviction": 0.10})
        flt = RegimeSignalFilter(mon)
        with patch(_PATCH, return_value=reg):
            snap = flt.compute()
            s = flt.to_signal(snap)
        assert s.value == pytest.approx(snap.filtered_composite)
