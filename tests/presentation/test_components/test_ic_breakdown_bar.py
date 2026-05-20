"""Tests for ICBreakdownBar component — to_html() only (no Streamlit)."""
from __future__ import annotations

import pytest

from presentation.ui.components.ic_breakdown_bar import ICBreakdownBar


SAMPLE_SIGNALS = {
    "Technical":  (0.42, 0.08, "ok"),
    "Macro":      (0.28, 0.11, "ok"),
    "Labour":     (0.15, 0.06, "ok"),
    "Sentiment":  (0.55, 0.05, "low_ic"),
    "Valuation":  (-0.20, 0.09, "ok"),
    "Surprise":   (0.35, 0.07, "ok"),
    "Volatility": (0.32, 0.12, "ok"),
}


class TestICBreakdownBarHtml:
    def test_all_signal_names_present(self) -> None:
        bar = ICBreakdownBar(signals=SAMPLE_SIGNALS, composite_value=0.34)
        html = bar.to_html()
        for name in SAMPLE_SIGNALS:
            assert name in html

    def test_composite_value_present(self) -> None:
        bar = ICBreakdownBar(signals=SAMPLE_SIGNALS, composite_value=0.34)
        assert "+0.340" in bar.to_html()

    def test_ic_values_present(self) -> None:
        bar = ICBreakdownBar(signals=SAMPLE_SIGNALS, composite_value=0.34)
        html = bar.to_html()
        assert "IC: 0.080" in html

    def test_regime_label_in_composito_row(self) -> None:
        bar = ICBreakdownBar(signals=SAMPLE_SIGNALS, composite_value=0.34, regime="bull")
        assert "BULL" in bar.to_html()

    def test_seven_signals_seven_rows(self) -> None:
        bar = ICBreakdownBar(signals=SAMPLE_SIGNALS, composite_value=0.34)
        html = bar.to_html()
        # 7 component rows (<tr>) + 1 composite row (<tr style=...)
        assert html.count("<tr") == 8

    def test_empty_signals_shows_empty_div(self) -> None:
        bar = ICBreakdownBar(signals={}, composite_value=0.0)
        assert "ic-breakdown-empty" in bar.to_html()

    def test_color_attribute_present(self) -> None:
        bar = ICBreakdownBar(signals=SAMPLE_SIGNALS, composite_value=0.0)
        assert "background:" in bar.to_html()

    def test_none_ic_shows_dash(self) -> None:
        sigs = {"Test": (0.3, None, "ok")}
        bar = ICBreakdownBar(signals=sigs, composite_value=0.3)
        assert "IC: —" in bar.to_html()


class TestICBreakdownBarDefaults:
    def test_default_composite_zero(self) -> None:
        bar = ICBreakdownBar()
        assert bar.composite_value == 0.0

    def test_default_regime_transition(self) -> None:
        bar = ICBreakdownBar()
        assert bar.regime == "transition"

    def test_default_signals_empty(self) -> None:
        bar = ICBreakdownBar()
        assert bar.signals == {}
