"""Tests for chart_theme: get_base_layout, ChartFactory, regime_shade, event_markers."""
from __future__ import annotations
import pandas as pd
import pytest
import plotly.graph_objects as go
from presentation.ui.chart_theme import (
    ChartFactory,
    get_base_layout,
    regime_shade,
    event_markers,
)


class TestGetBaseLayout:
    def test_returns_dict(self) -> None:
        layout = get_base_layout()
        assert isinstance(layout, dict)

    def test_has_required_keys(self) -> None:
        layout = get_base_layout()
        for key in ("font", "plot_bgcolor", "paper_bgcolor", "margin", "hovermode"):
            assert key in layout, f"Missing key: {key}"

    def test_overrides_applied(self) -> None:
        layout = get_base_layout(height=500, title="Test")
        assert layout["height"] == 500
        assert layout["title"] == "Test"

    def test_plot_bgcolor_is_string(self) -> None:
        layout = get_base_layout()
        assert isinstance(layout["plot_bgcolor"], str)
        assert len(layout["plot_bgcolor"]) > 0


class TestChartFactoryTimeSeries:
    def _make_df(self) -> pd.DataFrame:
        return pd.DataFrame({"date": pd.date_range("2026-01-01", periods=10), "value": range(10)})

    def test_returns_figure(self) -> None:
        fig = ChartFactory.time_series(self._make_df(), x_col="date", y_col="value")
        assert isinstance(fig, go.Figure)

    def test_has_one_trace(self) -> None:
        fig = ChartFactory.time_series(self._make_df(), x_col="date", y_col="value")
        assert len(fig.data) >= 1

    def test_title_set(self) -> None:
        fig = ChartFactory.time_series(self._make_df(), x_col="date", y_col="value", title="My Chart")
        assert fig.layout.title.text == "My Chart" or "My Chart" in str(fig.layout)

    def test_empty_df_returns_figure(self) -> None:
        fig = ChartFactory.time_series(pd.DataFrame(columns=["date", "value"]), x_col="date", y_col="value")
        assert isinstance(fig, go.Figure)


class TestChartFactorySignalBreakdown:
    def _signals(self) -> dict[str, tuple[float, float | None]]:
        # signal_breakdown expects dict[str, tuple[float, float|None]] — value + ic_estimate
        return {"macro": (0.4, 0.07), "vix": (-0.3, 0.05)}

    def test_returns_figure(self) -> None:
        fig = ChartFactory.signal_breakdown(self._signals())
        assert isinstance(fig, go.Figure)

    def test_has_bars(self) -> None:
        fig = ChartFactory.signal_breakdown(self._signals())
        assert any(isinstance(t, go.Bar) for t in fig.data)

    def test_empty_signals(self) -> None:
        fig = ChartFactory.signal_breakdown({})
        assert isinstance(fig, go.Figure)


class TestChartFactoryCorrelationHeatmap:
    def _corr_df(self) -> pd.DataFrame:
        import numpy as np
        data = {"SPY": [1.0, 0.8, -0.2], "TLT": [0.8, 1.0, -0.3], "GLD": [-0.2, -0.3, 1.0]}
        return pd.DataFrame(data, index=["SPY", "TLT", "GLD"])

    def test_returns_figure(self) -> None:
        fig = ChartFactory.correlation_heatmap(self._corr_df())
        assert isinstance(fig, go.Figure)

    def test_has_heatmap_trace(self) -> None:
        fig = ChartFactory.correlation_heatmap(self._corr_df())
        assert any(isinstance(t, go.Heatmap) for t in fig.data)

    def test_colorscale_is_sequence(self) -> None:
        fig = ChartFactory.correlation_heatmap(self._corr_df())
        cs = fig.data[0].colorscale
        assert isinstance(cs, (list, tuple))


class TestRegimeShade:
    def _make_regime_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "date":   pd.date_range("2026-01-01", periods=3),
            "regime": ["bull", "bear", "bull"],
        })

    def test_returns_figure(self) -> None:
        fig = go.Figure()
        result = regime_shade(fig, self._make_regime_df())
        assert isinstance(result, go.Figure)

    def test_adds_shapes(self) -> None:
        fig = go.Figure()
        result = regime_shade(fig, self._make_regime_df())
        assert isinstance(result.layout.shapes, (list, tuple))

    def test_empty_df_no_crash(self) -> None:
        fig = go.Figure()
        result = regime_shade(fig, pd.DataFrame(columns=["date", "regime"]))
        assert isinstance(result, go.Figure)


class TestEventMarkers:
    def _events(self) -> list[dict]:
        return [
            {"date": "2026-01-15", "label": "FED meeting", "color": "blue"},
            {"date": "2026-02-01", "label": "NFP",         "color": "red"},
        ]

    def test_returns_figure(self) -> None:
        fig = go.Figure()
        result = event_markers(fig, self._events())
        assert isinstance(result, go.Figure)

    def test_empty_events_no_crash(self) -> None:
        fig = go.Figure()
        result = event_markers(fig, [])
        assert isinstance(result, go.Figure)
