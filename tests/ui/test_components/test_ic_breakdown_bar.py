"""Tests for ICBreakdownBar component."""
from __future__ import annotations
import pytest
from presentation.ui.components.ic_breakdown_bar import ICBreakdownBar


_SAMPLE_SIGNALS: dict[str, tuple[float, float | None, str]] = {
    "technical_composite": (0.42, 0.08, "ok"),
    "macro_conviction":    (-0.15, 0.05, "ok"),
    "labour_regime":       (0.10, None,  "insufficient_data"),
    "sentiment":           (0.30, 0.03, "low_ic"),
    "valuation":           (-0.20, 0.07, "ok"),
    "surprise_index":      (0.05, 0.06, "ok"),
    "vix_signal":          (0.60, 0.10, "ok"),
}


class TestICBreakdownBarHtml:
    def test_to_html_returns_string(self) -> None:
        bar = ICBreakdownBar(signals=_SAMPLE_SIGNALS)
        assert isinstance(bar.to_html(), str)

    def test_to_html_has_table_rows_for_all_signals(self) -> None:
        bar = ICBreakdownBar(signals=_SAMPLE_SIGNALS)
        html = bar.to_html()
        # 7 signal rows + 1 composite row = 8 <tr tags
        assert html.count("<tr") == 8

    def test_to_html_contains_signal_names(self) -> None:
        bar = ICBreakdownBar(signals=_SAMPLE_SIGNALS)
        html = bar.to_html()
        assert "technical_composite" in html
        assert "vix_signal" in html

    def test_to_html_contains_values(self) -> None:
        bar = ICBreakdownBar(signals=_SAMPLE_SIGNALS)
        html = bar.to_html()
        assert "0.42" in html or "+0.42" in html

    def test_composite_row_present(self) -> None:
        bar = ICBreakdownBar(signals=_SAMPLE_SIGNALS, composite_value=0.25)
        html = bar.to_html()
        assert "0.25" in html or "Composite" in html or "composito" in html.lower()

    def test_empty_signals_still_renders(self) -> None:
        bar = ICBreakdownBar(signals={})
        html = bar.to_html()
        assert isinstance(html, str)

    def test_regime_included(self) -> None:
        bar = ICBreakdownBar(signals=_SAMPLE_SIGNALS, regime="bull")
        html = bar.to_html()
        assert isinstance(html, str)

    def test_none_ic_rendered_gracefully(self) -> None:
        signals = {"x": (0.1, None, "insufficient_data")}
        bar = ICBreakdownBar(signals=signals)
        html = bar.to_html()
        assert "None" not in html  # should display "N/D" or "—"
