"""chart_theme — Plotly layout factory and regime/event annotations.

Every chart in the dashboard must use ``get_base_layout()`` as its base
and ``ChartFactory`` for standard chart types.  Zero Plotly config inline
in page files (Rule 20: no hardcoded values).

Public API:
    get_base_layout(**overrides) -> dict
    regime_shade(fig, regime_df) -> go.Figure
    event_markers(fig, events) -> go.Figure
    ChartFactory.time_series(...)
    ChartFactory.signal_breakdown(...)
    ChartFactory.correlation_heatmap(...)
    ChartFactory.pie_allocation(...)
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go

from presentation.ui.design_tokens import TOKENS

__all__ = [
    "ChartFactory",
    "event_markers",
    "get_base_layout",
    "regime_shade",
]


def get_base_layout(**overrides: Any) -> dict:
    """Plotly layout dict consistent with DESIGN_TOKENS.

    Args:
        **overrides: Any Plotly layout keys to override.

    Returns:
        A dict ready for ``fig.update_layout(**get_base_layout())``.
    """
    t = TOKENS
    base: dict[str, Any] = {
        "font": {
            "family": t.typography.font_family_base,
            "size": 13,
            "color": t.colors.text_primary,
        },
        "plot_bgcolor": t.plotly.plot_bgcolor,
        "paper_bgcolor": t.plotly.paper_bgcolor,
        "margin": {"t": 40, "b": 30, "l": 50, "r": 20},
        "xaxis": {
            "showgrid": False,
            "linecolor": t.colors.bg_overlay,
            "tickfont": {"size": 11},
        },
        "yaxis": {
            "gridcolor": t.colors.bg_overlay,
            "tickfont": {"size": 11},
        },
        "hovermode": "x unified",
        "legend": {
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.01,
            "xanchor": "left",
            "x": 0,
        },
    }
    base.update(overrides)
    return base


def regime_shade(
    fig: go.Figure,
    regime_df: pd.DataFrame,
    date_col: str = "date",
    regime_col: str = "regime",
) -> go.Figure:
    """Add semi-transparent shading per market regime to a time-series chart.

    Args:
        fig:        Plotly Figure to annotate.
        regime_df:  DataFrame with ``date_col`` and ``regime_col`` columns.
                    Regime values: "bull" | "bear" | "stress" | "transition".
        date_col:   Name of the date column.
        regime_col: Name of the regime column.

    Returns:
        The same figure with vrect shapes added (in-place + returned).
    """
    if regime_df.empty:
        return fig

    shade_colors: dict[str, str] = {
        "bull":       TOKENS.colors.shade_bull,
        "bear":       TOKENS.colors.shade_bear,
        "stress":     TOKENS.colors.shade_stress,
        "transition": TOKENS.colors.shade_transition,
    }

    df = regime_df.sort_values(date_col).copy()
    df["_group"] = (df[regime_col] != df[regime_col].shift()).cumsum()

    for _, grp in df.groupby("_group"):
        regime = grp[regime_col].iloc[0]
        color = shade_colors.get(str(regime).lower())
        if color is None:
            continue
        fig.add_vrect(
            x0=grp[date_col].min(),
            x1=grp[date_col].max(),
            fillcolor=color,
            layer="below",
            line_width=0,
        )
    return fig


def event_markers(
    fig: go.Figure,
    events: list[dict],
) -> go.Figure:
    """Add annotated vertical lines for key events.

    Args:
        fig:    Plotly Figure to annotate.
        events: List of dicts with keys:
                ``date`` (str|datetime), ``label`` (str), ``color`` (str, optional).

    Returns:
        The same figure with vline annotations added (in-place + returned).
    """
    for ev in events:
        x = pd.Timestamp(ev["date"]) if isinstance(ev["date"], str) else ev["date"]
        fig.add_vline(
            x=x.timestamp() * 1000,  # Plotly expects ms epoch for date axes
            line_width=1,
            line_dash="dot",
            line_color=ev.get("color", TOKENS.colors.text_muted),
            annotation_text=ev.get("label", ""),
            annotation_position="top left",
            annotation_font_size=10,
        )
    return fig


class ChartFactory:
    """Factory for all standard chart types used in the dashboard.

    Every method returns a ``go.Figure`` with the base Plotly theme applied.
    Pass the result to ``st.plotly_chart(fig, use_container_width=True)``.
    """

    @staticmethod
    def time_series(
        df: pd.DataFrame,
        x_col: str,
        y_col: str,
        title: str = "",
        color: str | None = None,
        y_format: str = "number",
        regime_df: pd.DataFrame | None = None,
        events: list[dict] | None = None,
    ) -> go.Figure:
        """Line chart for time-series data with optional regime shading.

        Args:
            df:         DataFrame with at least ``x_col`` and ``y_col``.
            x_col:      Name of the x-axis (date) column.
            y_col:      Name of the y-axis column.
            title:      Chart title.
            color:      Line color; defaults to TOKENS chart_primary.
            y_format:   "number" | "percent" | "currency"
            regime_df:  Optional DataFrame for regime shading (see regime_shade).
            events:     Optional list of event dicts (see event_markers).

        Returns:
            Configured Plotly Figure.
        """
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df[x_col],
            y=df[y_col],
            mode="lines",
            line={"color": color or TOKENS.colors.chart_primary, "width": 2},
            hovertemplate="%{x|%d %b %Y}<br><b>%{y:.2f}</b><extra></extra>",
        ))

        tick_format = {"percent": ".1%", "currency": ",.0f"}.get(y_format, ".2f")
        layout = get_base_layout(title={"text": title, "font": {"size": 14}})
        layout["yaxis"]["tickformat"] = tick_format
        fig.update_layout(**layout)

        if regime_df is not None and not regime_df.empty:
            regime_shade(fig, regime_df)
        if events:
            event_markers(fig, events)
        return fig

    @staticmethod
    def signal_breakdown(
        signals: dict[str, tuple[float, float | None]],
        regime: str = "transition",
        title: str = "Composite Signal — Breakdown",
    ) -> go.Figure:
        """Horizontal bar chart for signal-component breakdown.

        Args:
            signals: ``{name: (value, ic_estimate)}`` where value ∈ [-1, 1].
            regime:  Current market regime (informational only for now).
            title:   Chart title.

        Returns:
            Configured Plotly Figure.
        """
        names = list(signals.keys())
        values = [float(v) for v, _ in signals.values()]
        colors = [TOKENS.colors.signal_color(v) for v in values]

        fig = go.Figure(go.Bar(
            y=names,
            x=values,
            orientation="h",
            marker_color=colors,
            hovertemplate="<b>%{y}</b>: %{x:+.3f}<extra></extra>",
            text=[f"{v:+.3f}" for v in values],
            textposition="auto",
        ))
        fig.add_vline(x=0, line_width=1, line_color=TOKENS.colors.text_muted)
        layout = get_base_layout(title={"text": title, "font": {"size": 14}})
        layout["xaxis"].update({"range": [-1.1, 1.1], "tickformat": "+.1f"})
        fig.update_layout(**layout)
        return fig

    @staticmethod
    def correlation_heatmap(
        corr_matrix: pd.DataFrame,
        title: str = "Matrice Correlazioni",
        fmt: str = ".2f",
    ) -> go.Figure:
        """Diverging RdYlGn heatmap for a correlation matrix.

        Args:
            corr_matrix: Square DataFrame with correlation values in [-1, 1].
            title:       Chart title.
            fmt:         Number format for text annotations.

        Returns:
            Configured Plotly Figure.
        """
        fig = go.Figure(go.Heatmap(
            z=corr_matrix.values,
            x=list(corr_matrix.columns),
            y=list(corr_matrix.index),
            colorscale="RdYlGn",
            zmin=-1,
            zmax=1,
            text=[[f"{v:{fmt}}" for v in row] for row in corr_matrix.values],
            texttemplate="%{text}",
            hovertemplate="<b>%{y}</b> vs <b>%{x}</b>: %{z:.3f}<extra></extra>",
        ))
        fig.update_layout(**get_base_layout(title={"text": title, "font": {"size": 14}}))
        return fig

    @staticmethod
    def pie_allocation(
        labels: list[str],
        values: list[float],
        title: str = "Allocazione",
    ) -> go.Figure:
        """Pie chart for portfolio or sector allocation.

        Args:
            labels: Slice labels.
            values: Slice values (need not sum to 100).
            title:  Chart title.

        Returns:
            Configured Plotly Figure.
        """
        palette = [
            TOKENS.colors.chart_primary,
            TOKENS.colors.chart_secondary,
            TOKENS.colors.chart_accent,
            "#7f77dd",
            "#5dcaa5",
            "#ef9f27",
            "#e05c6b",
            "#47a8bd",
        ]
        fig = go.Figure(go.Pie(
            labels=labels,
            values=values,
            textinfo="label+percent",
            hovertemplate="<b>%{label}</b>: %{value:.1f}%<extra></extra>",
            marker_colors=palette[: len(labels)],
        ))
        fig.update_layout(**get_base_layout(
            title={"text": title, "font": {"size": 14}},
            showlegend=True,
        ))
        return fig
