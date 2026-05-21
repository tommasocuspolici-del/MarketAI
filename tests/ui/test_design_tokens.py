"""Tests for design tokens: TOKENS, signal_color, regime_color, ic_color."""
from __future__ import annotations
import pytest
from presentation.ui.design_tokens import TOKENS


class TestTokensSingleton:
    def test_tokens_not_none(self) -> None:
        assert TOKENS is not None

    def test_tokens_has_colors(self) -> None:
        assert hasattr(TOKENS, "colors")

    def test_tokens_has_typography(self) -> None:
        assert hasattr(TOKENS, "typography")

    def test_tokens_has_spacing(self) -> None:
        assert hasattr(TOKENS, "spacing")


class TestSignalColor:
    @pytest.mark.parametrize("value,expected_contains", [
        (0.8,   "#2d7a4f"),   # strong bull
        (0.2,   "#5cba86"),   # bull
        (0.0,   "#888780"),   # neutral
        (-0.2,  "#d85a30"),   # bear
        (-0.8,  "#a32d2d"),   # strong bear
    ])
    def test_signal_color_boundaries(self, value: float, expected_contains: str) -> None:
        color = TOKENS.colors.signal_color(value)
        assert color == expected_contains, f"value={value}: got {color!r}"

    def test_signal_color_clamps_above_one(self) -> None:
        color = TOKENS.colors.signal_color(5.0)
        assert color == TOKENS.colors.signal_strong_bull

    def test_signal_color_clamps_below_minus_one(self) -> None:
        color = TOKENS.colors.signal_color(-5.0)
        assert color == TOKENS.colors.signal_strong_bear

    def test_signal_color_returns_hex(self) -> None:
        color = TOKENS.colors.signal_color(0.5)
        assert color.startswith("#")
        assert len(color) == 7


class TestRegimeColor:
    @pytest.mark.parametrize("regime", ["bull", "bear", "stress", "transition", "unknown"])
    def test_regime_color_returns_string(self, regime: str) -> None:
        color = TOKENS.colors.regime_color(regime)
        assert isinstance(color, str)

    def test_bull_regime_is_green(self) -> None:
        color = TOKENS.colors.regime_color("bull")
        assert "#" in color

    def test_stress_regime_different_from_bull(self) -> None:
        bull_color = TOKENS.colors.regime_color("bull")
        stress_color = TOKENS.colors.regime_color("stress")
        assert bull_color != stress_color


class TestIcColor:
    def test_ok_flag_returns_quality_good(self) -> None:
        color = TOKENS.colors.ic_color(0.08, flag="ok")
        assert isinstance(color, str)

    def test_low_ic_flag(self) -> None:
        color = TOKENS.colors.ic_color(0.01, flag="low_ic")
        assert color == TOKENS.colors.ic_low

    def test_degraded_flag(self) -> None:
        color = TOKENS.colors.ic_color(None, flag="degraded")
        assert color == TOKENS.colors.ic_degraded

    def test_none_ic_returns_unknown(self) -> None:
        color = TOKENS.colors.ic_color(None, flag="ok")
        assert color == TOKENS.colors.ic_unknown

    def test_all_colors_are_hex(self) -> None:
        for color in [
            TOKENS.colors.ic_low, TOKENS.colors.ic_degraded, TOKENS.colors.ic_unknown
        ]:
            assert color.startswith("#")
