"""Tests for KpiCard component — to_html() only (no Streamlit)."""
from __future__ import annotations
import pytest
from presentation.ui.components.kpi_card import KpiCard


class TestKpiCardHtml:
    def test_to_html_returns_string(self) -> None:
        card = KpiCard(title="Sharpe", value=1.42)
        assert isinstance(card.to_html(), str)

    def test_to_html_contains_title(self) -> None:
        card = KpiCard(title="Max DD", value=-0.12)
        assert "Max DD" in card.to_html()

    def test_to_html_formats_float(self) -> None:
        card = KpiCard(title="Return", value=0.153)
        html = card.to_html()
        assert "0.15" in html or "15" in html  # formatted value present

    def test_to_html_with_unit(self) -> None:
        card = KpiCard(title="VaR", value=2.5, unit="%")
        html = card.to_html()
        assert "%" in html

    def test_to_html_with_positive_delta(self) -> None:
        card = KpiCard(title="Return", value=10.0, delta=2.5)
        html = card.to_html()
        assert "+2.5" in html or "2.5" in html

    def test_to_html_with_negative_delta(self) -> None:
        card = KpiCard(title="Return", value=-3.0, delta=-1.2)
        html = card.to_html()
        assert "-1.2" in html

    def test_to_html_quality_ok_has_dot(self) -> None:
        card = KpiCard(title="IC", value=0.08, quality_flag="ok")
        html = card.to_html()
        assert "●" in html

    def test_to_html_quality_low_ic(self) -> None:
        card = KpiCard(title="IC", value=0.01, quality_flag="low_ic")
        html = card.to_html()
        assert "◐" in html

    def test_to_html_quality_insufficient_data(self) -> None:
        card = KpiCard(title="IC", value=0.0, quality_flag="insufficient_data")
        html = card.to_html()
        assert "○" in html

    def test_to_html_string_value(self) -> None:
        card = KpiCard(title="Regime", value="bull")
        assert "bull" in card.to_html()

    def test_to_html_with_icon(self) -> None:
        card = KpiCard(title="Sharpe", value=1.2, icon="📊")
        assert "📊" in card.to_html()

    def test_no_delta_no_delta_string(self) -> None:
        card = KpiCard(title="Score", value=42.0)
        html = card.to_html()
        # No delta line when delta is None
        assert "None" not in html


class TestKpiCardFormatValue:
    def test_large_float_formatted(self) -> None:
        card = KpiCard(title="X", value=1_234_567.89)
        html = card.to_html()
        # Should not be a raw unformatted number
        assert "1234567.89" not in html

    def test_zero_value(self) -> None:
        card = KpiCard(title="X", value=0.0)
        html = card.to_html()
        assert html  # non-empty

    def test_negative_value(self) -> None:
        card = KpiCard(title="X", value=-42.5)
        assert "-" in card.to_html() or "42" in card.to_html()
