"""Tests for SignalBadge component."""
from __future__ import annotations
import pytest
from presentation.ui.components.signal_badge import SignalBadge


class TestSignalBadgeDirection:
    @pytest.mark.parametrize("value,expected", [
        (1.0,   "RIALZISTA"),
        (0.5,   "RIALZISTA"),
        (0.31,  "RIALZISTA"),
        (0.3,   "lieve ↑"),      # boundary: v > 0.3 is strict, so 0.3 → lieve ↑
        (0.2,   "lieve ↑"),
        (0.06,  "lieve ↑"),
        (0.05,  "NEUTRO"),       # boundary: v > 0.05 strict, so 0.05 → NEUTRO
        (0.0,   "NEUTRO"),
        (-0.04, "NEUTRO"),
        (-0.05, "lieve ↓"),      # boundary: v > -0.05 strict, so -0.05 → lieve ↓
        (-0.2,  "lieve ↓"),
        (-0.29, "lieve ↓"),
        (-0.3,  "RIBASSISTA"),   # boundary: v > -0.3 strict, so -0.3 → RIBASSISTA
        (-0.5,  "RIBASSISTA"),
        (-1.0,  "RIBASSISTA"),
    ])
    def test_direction_boundaries(self, value: float, expected: str) -> None:
        badge = SignalBadge(name="Test", value=value)
        assert badge.direction == expected, f"value={value}: got {badge.direction!r}, expected {expected!r}"

    def test_direction_clip_above_one(self) -> None:
        badge = SignalBadge(name="X", value=2.0)
        assert badge.direction == "RIALZISTA"

    def test_direction_clip_below_minus_one(self) -> None:
        badge = SignalBadge(name="X", value=-2.0)
        assert badge.direction == "RIBASSISTA"


class TestSignalBadgeColor:
    def test_color_strong_bull(self) -> None:
        badge = SignalBadge(name="X", value=0.8)
        color = badge.color
        assert isinstance(color, str)
        assert color.startswith("#")

    def test_color_strong_bear(self) -> None:
        badge = SignalBadge(name="X", value=-0.8)
        color = badge.color
        assert color != badge.__class__(name="X", value=0.8).color  # different from bull

    def test_color_neutral(self) -> None:
        badge = SignalBadge(name="X", value=0.0)
        assert isinstance(badge.color, str)


class TestSignalBadgeHtml:
    def test_to_html_contains_name(self) -> None:
        badge = SignalBadge(name="Technical", value=0.42)
        assert "Technical" in badge.to_html()

    def test_to_html_contains_value(self) -> None:
        badge = SignalBadge(name="X", value=0.42)
        assert "0.42" in badge.to_html() or "+0.42" in badge.to_html()

    def test_to_html_contains_direction(self) -> None:
        badge = SignalBadge(name="X", value=0.5)
        html = badge.to_html()
        assert "RIALZISTA" in html

    def test_to_html_with_ic(self) -> None:
        badge = SignalBadge(name="X", value=0.3, ic_estimate=0.072)
        assert "0.072" in badge.to_html() or "IC" in badge.to_html()

    def test_to_html_without_ic(self) -> None:
        badge = SignalBadge(name="X", value=0.3, ic_estimate=None)
        html = badge.to_html()
        assert "IC:None" not in html

    def test_to_html_has_color_style(self) -> None:
        badge = SignalBadge(name="Macro", value=0.6)
        html = badge.to_html()
        assert "color:" in html

    def test_defaults(self) -> None:
        badge = SignalBadge(name="X", value=0.1)
        assert badge.confidence == 1.0
        assert badge.ic_estimate is None
        assert badge.quality_flag == "ok"
