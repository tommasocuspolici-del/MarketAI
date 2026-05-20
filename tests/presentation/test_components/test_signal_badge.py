"""Tests for SignalBadge component — to_html() only (no Streamlit)."""
from __future__ import annotations

import pytest

from presentation.ui.components.signal_badge import SignalBadge


class TestSignalBadgeDirection:
    @pytest.mark.parametrize("value,expected", [
        (0.8,   "RIALZISTA"),
        (0.31,  "RIALZISTA"),
        (0.2,   "lieve ↑"),
        (0.06,  "lieve ↑"),
        (0.0,   "NEUTRO"),
        (-0.04, "NEUTRO"),
        (-0.2,  "lieve ↓"),
        (-0.31, "RIBASSISTA"),
        (-0.8,  "RIBASSISTA"),
    ])
    def test_direction_thresholds(self, value: float, expected: str) -> None:
        assert SignalBadge("sig", value).direction == expected

    def test_direction_boundary_at_plus_03(self) -> None:
        # v > 0.3 → RIALZISTA; at exactly 0.3 → "lieve ↑"
        assert SignalBadge("sig", 0.3).direction == "lieve ↑"
        assert SignalBadge("sig", 0.31).direction == "RIALZISTA"

    def test_direction_boundary_at_minus_03(self) -> None:
        # v > -0.3 → "lieve ↓"; at exactly -0.3 → "RIBASSISTA"
        assert SignalBadge("sig", -0.3).direction == "RIBASSISTA"
        assert SignalBadge("sig", -0.29).direction == "lieve ↓"


class TestSignalBadgeHtml:
    def test_name_in_html(self) -> None:
        html = SignalBadge("Technical", 0.5).to_html()
        assert "Technical" in html

    def test_value_formatted_signed(self) -> None:
        html = SignalBadge("sig", 0.42).to_html()
        assert "+0.420" in html

    def test_negative_value_formatted(self) -> None:
        html = SignalBadge("sig", -0.3).to_html()
        assert "-0.300" in html

    def test_ic_shown_when_provided(self) -> None:
        html = SignalBadge("sig", 0.5, ic_estimate=0.08).to_html()
        assert "IC:0.080" in html

    def test_ic_omitted_when_none(self) -> None:
        html = SignalBadge("sig", 0.5).to_html()
        assert "IC:" not in html

    def test_color_attribute_present(self) -> None:
        html = SignalBadge("sig", 0.5).to_html()
        assert "color:" in html

    def test_clamps_above_one(self) -> None:
        # direction should not crash for out-of-range values
        assert SignalBadge("sig", 2.0).direction == "RIALZISTA"

    def test_clamps_below_minus_one(self) -> None:
        assert SignalBadge("sig", -2.0).direction == "RIBASSISTA"


class TestSignalBadgeColor:
    def test_bull_color_for_positive(self) -> None:
        badge = SignalBadge("sig", 0.6)
        from presentation.ui.design_tokens import TOKENS
        assert badge.color == TOKENS.colors.signal_strong_bull

    def test_bear_color_for_negative(self) -> None:
        badge = SignalBadge("sig", -0.6)
        from presentation.ui.design_tokens import TOKENS
        assert badge.color == TOKENS.colors.signal_strong_bear

    def test_neutral_color_near_zero(self) -> None:
        badge = SignalBadge("sig", 0.0)
        from presentation.ui.design_tokens import TOKENS
        assert badge.color == TOKENS.colors.signal_neutral
