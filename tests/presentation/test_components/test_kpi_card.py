"""Tests for KpiCard BaseComponent — to_html() only (no Streamlit)."""
from __future__ import annotations

import pytest

from presentation.ui.components.kpi_card import KpiCard


class TestKpiCardFormatValue:
    def test_large_number_millions(self) -> None:
        assert "1.2M" in KpiCard("Test", 1_234_567.0).to_html()

    def test_thousands_comma_separated(self) -> None:
        assert "4,523" in KpiCard("Test", 4_523.0).to_html()

    def test_small_decimal(self) -> None:
        assert "18.45" in KpiCard("Test", 18.45).to_html()

    def test_string_value_passthrough(self) -> None:
        card = KpiCard("Test", "N/A")
        assert "N/A" in card.to_html()

    def test_zero(self) -> None:
        assert "0.00" in KpiCard("Test", 0.0).to_html()

    def test_negative_large(self) -> None:
        assert "-1,234" in KpiCard("Test", -1234.0).to_html()


class TestKpiCardDelta:
    def test_positive_delta_shows_plus(self) -> None:
        html = KpiCard("Test", 100.0, delta=2.5).to_html()
        assert "+2.5%" in html

    def test_negative_delta_shows_minus(self) -> None:
        html = KpiCard("Test", 100.0, delta=-1.3).to_html()
        assert "-1.3%" in html

    def test_delta_label_included(self) -> None:
        html = KpiCard("Test", 100.0, delta=1.0, delta_label="vs 1W").to_html()
        assert "vs 1W" in html

    def test_no_delta_no_percent(self) -> None:
        html = KpiCard("Test", 100.0).to_html()
        assert "%" not in html


class TestKpiCardQualityFlag:
    @pytest.mark.parametrize("flag,symbol", [
        ("ok",                "●"),
        ("low_ic",            "◐"),
        ("insufficient_data", "○"),
        ("stale",             "◌"),
    ])
    def test_quality_dot_present(self, flag: str, symbol: str) -> None:
        html = KpiCard("Test", 1.0, quality_flag=flag).to_html()
        assert symbol in html

    def test_unknown_flag_defaults_to_circle(self) -> None:
        html = KpiCard("Test", 1.0, quality_flag="bogus").to_html()
        assert "○" in html


class TestKpiCardHtml:
    def test_title_in_html(self) -> None:
        assert "VIX" in KpiCard("VIX", 18.4).to_html()

    def test_unit_in_html(self) -> None:
        html = KpiCard("Gold", 2350.0, unit=" USD").to_html()
        assert "USD" in html

    def test_icon_in_html(self) -> None:
        html = KpiCard("BTC", 60000.0, icon="₿").to_html()
        assert "₿" in html

    def test_kpi_card_class_present(self) -> None:
        assert 'class="kpi-card"' in KpiCard("Test", 1.0).to_html()


class TestKpiCardDefaults:
    def test_default_unit_empty(self) -> None:
        card = KpiCard("X", 1.0)
        assert card.unit == ""

    def test_default_quality_ok(self) -> None:
        card = KpiCard("X", 1.0)
        assert card.quality_flag == "ok"

    def test_default_delta_none(self) -> None:
        card = KpiCard("X", 1.0)
        assert card.delta is None
