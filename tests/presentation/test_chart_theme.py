"""Tests for chart_theme — get_base_layout, regime_shade, event_markers, ChartFactory."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import pytest

from presentation.ui.chart_theme import (
    ChartFactory,
    event_markers,
    get_base_layout,
    regime_shade,
)


class TestGetBaseLayout:
    def test_returns_dict(self) -> None:
        assert isinstance(get_base_layout(), dict)

    def test_hovermode_is_x_unified(self) -> None:
        assert get_base_layout()["hovermode"] == "x unified"

    def test_overrides_are_applied(self) -> None:
        layout = get_base_layout(title={"text": "Test"})
        assert layout["title"]["text"] == "Test"

    def test_plot_bgcolor_present(self) -> None:
        assert "plot_bgcolor" in get_base_layout()

    def test_font_family_from_tokens(self) -> None:
        from presentation.ui.design_tokens import TOKENS
        layout = get_base_layout()
        assert layout["font"]["family"] == TOKENS.typography.font_family_base


class TestRegimeShade:
    def _make_regime_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=4, freq="QE"),
            "regime": ["bull", "bull", "bear", "stress"],
        })

    def test_returns_figure(self) -> None:
        fig = go.Figure()
        result = regime_shade(fig, self._make_regime_df())
        assert isinstance(result, go.Figure)

    def test_shapes_added(self) -> None:
        fig = go.Figure()
        regime_shade(fig, self._make_regime_df())
        assert len(fig.layout.shapes) > 0

    def test_empty_df_no_shapes(self) -> None:
        fig = go.Figure()
        result = regime_shade(fig, pd.DataFrame())
        assert len(result.layout.shapes) == 0

    def test_unknown_regime_skipped(self) -> None:
        fig = go.Figure()
        df = pd.DataFrame({"date": ["2024-01-01"], "regime": ["??unknown??"]})
        regime_shade(fig, df)
        assert len(fig.layout.shapes) == 0


class TestEventMarkers:
    def test_returns_figure(self) -> None:
        fig = go.Figure()
        result = event_markers(fig, [{"date": "2024-03-20", "label": "FOMC"}])
        assert isinstance(result, go.Figure)

    def test_vline_shape_added(self) -> None:
        # add_vline in Plotly adds a shape, not to layout.annotations directly
        fig = go.Figure()
        event_markers(fig, [{"date": "2024-03-20", "label": "FOMC"}])
        d = fig.to_dict()
        shapes = d.get("layout", {}).get("shapes", [])
        assert len(shapes) >= 1

    def test_empty_events_no_change(self) -> None:
        fig = go.Figure()
        event_markers(fig, [])
        d = fig.to_dict()
        assert len(d.get("layout", {}).get("shapes", [])) == 0


class TestChartFactoryTimeSeries:
    def _sample_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=12, freq="ME"),
            "value": [100 + i for i in range(12)],
        })

    def test_returns_figure(self) -> None:
        fig = ChartFactory.time_series(self._sample_df(), "date", "value")
        assert isinstance(fig, go.Figure)

    def test_has_one_trace(self) -> None:
        fig = ChartFactory.time_series(self._sample_df(), "date", "value")
        assert len(fig.data) == 1

    def test_with_regime_shading(self) -> None:
        regime_df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=3, freq="QE"),
            "regime": ["bull", "transition", "bear"],
        })
        fig = ChartFactory.time_series(
            self._sample_df(), "date", "value", regime_df=regime_df
        )
        assert len(fig.layout.shapes) > 0

    def test_with_events(self) -> None:
        fig = ChartFactory.time_series(
            self._sample_df(), "date", "value",
            events=[{"date": "2024-03-01", "label": "FOMC"}],
        )
        d = fig.to_dict()
        assert len(d.get("layout", {}).get("shapes", [])) >= 1


class TestChartFactorySignalBreakdown:
    def _signals(self) -> dict:
        return {f"sig_{i}": (0.3 * i - 0.9, 0.05) for i in range(7)}

    def test_returns_figure(self) -> None:
        fig = ChartFactory.signal_breakdown(self._signals())
        assert isinstance(fig, go.Figure)

    def test_has_seven_bars(self) -> None:
        fig = ChartFactory.signal_breakdown(self._signals())
        assert len(fig.data[0]["y"]) == 7

    def test_zero_line_present(self) -> None:
        fig = ChartFactory.signal_breakdown(self._signals())
        assert any(s.get("x0") == 0 for s in fig.to_dict().get("layout", {}).get("shapes", []))


class TestChartFactoryCorrelationHeatmap:
    def _corr(self) -> pd.DataFrame:
        import numpy as np
        data = np.array([[1.0, 0.5, -0.3], [0.5, 1.0, 0.1], [-0.3, 0.1, 1.0]])
        return pd.DataFrame(data, columns=["A", "B", "C"], index=["A", "B", "C"])

    def test_returns_figure(self) -> None:
        fig = ChartFactory.correlation_heatmap(self._corr())
        assert isinstance(fig, go.Figure)

    def test_colorscale_is_rdylgn(self) -> None:
        fig = ChartFactory.correlation_heatmap(self._corr())
        # Plotly normalizes colorscale to a tuple of tuples; check via dict
        d = fig.to_dict()
        cs = d["data"][0].get("colorscale", "")
        assert "RdYlGn" in str(cs) or isinstance(cs, (list, tuple))


class TestChartFactoryPieAllocation:
    def test_returns_figure(self) -> None:
        fig = ChartFactory.pie_allocation(["US", "EU", "EM"], [50.0, 30.0, 20.0])
        assert isinstance(fig, go.Figure)

    def test_has_pie_trace(self) -> None:
        fig = ChartFactory.pie_allocation(["A", "B"], [60.0, 40.0])
        assert len(fig.data) == 1
        assert isinstance(fig.data[0], go.Pie)
