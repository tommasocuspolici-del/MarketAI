"""Tests for DesignTokens — signal_color, regime_color, ic_color boundaries."""
from __future__ import annotations

import pytest

from presentation.ui.design_tokens import TOKENS
from presentation.ui.theme import load_design_tokens


class TestSignalColor:
    @pytest.mark.parametrize("value,attr", [
        (0.9,   "signal_strong_bull"),
        (0.3,   "signal_bull"),
        (0.0,   "signal_neutral"),
        (-0.3,  "signal_bear"),
        (-0.9,  "signal_strong_bear"),
    ])
    def test_signal_color_buckets(self, value: float, attr: str) -> None:
        expected = getattr(TOKENS.colors, attr)
        assert TOKENS.colors.signal_color(value) == expected

    def test_signal_color_boundary_plus_05(self) -> None:
        # exactly 0.5 → bull (not strong_bull, threshold is > 0.5)
        assert TOKENS.colors.signal_color(0.5) == TOKENS.colors.signal_bull

    def test_signal_color_boundary_plus_051(self) -> None:
        assert TOKENS.colors.signal_color(0.51) == TOKENS.colors.signal_strong_bull

    def test_signal_color_clamps_above_one(self) -> None:
        assert TOKENS.colors.signal_color(2.0) == TOKENS.colors.signal_strong_bull

    def test_signal_color_clamps_below_minus_one(self) -> None:
        assert TOKENS.colors.signal_color(-2.0) == TOKENS.colors.signal_strong_bear


class TestRegimeColor:
    @pytest.mark.parametrize("regime,attr", [
        ("bull",       "regime_bull"),
        ("bear",       "regime_bear"),
        ("stress",     "regime_stress"),
        ("transition", "regime_transition"),
    ])
    def test_known_regimes(self, regime: str, attr: str) -> None:
        expected = getattr(TOKENS.colors, attr)
        assert TOKENS.colors.regime_color(regime) == expected

    def test_unknown_regime_returns_neutral(self) -> None:
        assert TOKENS.colors.regime_color("unknown") == TOKENS.colors.neutral

    def test_case_insensitive(self) -> None:
        assert TOKENS.colors.regime_color("BULL") == TOKENS.colors.regime_color("bull")


class TestIcColor:
    def test_ok_returns_quality_good(self) -> None:
        result = TOKENS.colors.ic_color(0.08, flag="ok")
        assert result == TOKENS.colors.quality_good

    def test_low_ic_flag(self) -> None:
        assert TOKENS.colors.ic_color(0.02, flag="low_ic") == TOKENS.colors.ic_low

    def test_degraded_flag(self) -> None:
        assert TOKENS.colors.ic_color(None, flag="degraded") == TOKENS.colors.ic_degraded

    def test_none_ic_returns_unknown(self) -> None:
        assert TOKENS.colors.ic_color(None, flag="ok") == TOKENS.colors.ic_unknown


class TestTokensSingleton:
    def test_tokens_is_same_object(self) -> None:
        from presentation.ui.design_tokens import TOKENS as t2
        assert TOKENS is t2

    def test_load_design_tokens_cached(self) -> None:
        t1 = load_design_tokens()
        t2 = load_design_tokens()
        assert t1 is t2

    def test_new_color_fields_present(self) -> None:
        c = TOKENS.colors
        assert c.signal_strong_bull
        assert c.shade_bull
        assert c.chart_primary
        assert c.ic_low
