"""KPI card component — labeled metric tile.

Two patterns coexist:
  - Legacy functional: ``render_kpi_card()`` / ``render_kpi_row()``  (v6.0)
  - New class-based:   ``KpiCard(BaseComponent)``                     (v8.2)

New pages use ``KpiCard``; legacy pages keep ``render_kpi_card``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from presentation.ui.components.base import BaseComponent

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "8.2.0"

__all__ = ["KpiCard", "render_kpi_card", "render_kpi_row"]


# ── Quality indicator symbols ─────────────────────────────────────────────────
_QUALITY_DOTS: dict[str, str] = {
    "ok":                "●",
    "low_ic":            "◐",
    "insufficient_data": "○",
    "stale":             "◌",
}


@dataclass
class KpiCard(BaseComponent):
    """Metric tile with delta, quality flag, and optional tooltip.

    Args:
        title:        Short label (≤ 20 chars recommended).
        value:        Numeric value or pre-formatted string.
        unit:         Unit suffix (e.g. ``"%"``, ``"$"``).
        delta:        Signed delta (positive = green, negative = red).
        delta_label:  Short description shown next to delta (e.g. ``"vs 1W"``).
        quality_flag: Signal quality: ``"ok"`` | ``"low_ic"`` |
                      ``"insufficient_data"`` | ``"stale"``.
        icon:         Optional emoji or text icon prefix.
        tooltip:      Help text shown on hover in Streamlit.

    Example::

        card = KpiCard("VIX", 18.4, delta=-2.1, delta_label="vs ieri")
        assert "+2" not in card.to_html()   # negative delta
        card.render()  # pragma: no cover
    """

    title: str
    value: float | str
    unit: str = ""
    delta: float | None = None
    delta_label: str = ""
    quality_flag: str = "ok"
    icon: str = ""
    tooltip: str = ""

    def _format_value(self) -> str:
        if isinstance(self.value, str):
            return self.value
        v = float(self.value)
        if abs(v) >= 1_000_000:
            return f"{v / 1_000_000:.1f}M"
        if abs(v) >= 1_000:
            return f"{v:,.0f}"
        return f"{v:.2f}"

    def _quality_dot(self) -> str:
        return _QUALITY_DOTS.get(self.quality_flag, "○")

    def to_html(self) -> str:
        """Return pure HTML — testable without Streamlit."""
        delta_str = ""
        if self.delta is not None:
            sign = "+" if self.delta >= 0 else ""
            delta_str = f"{sign}{self.delta:.1f}%"
            if self.delta_label:
                delta_str += f" {self.delta_label}"
        icon_prefix = f"{self.icon} " if self.icon else ""
        return (
            f'<div class="kpi-card">'
            f'<span class="kpi-title">{icon_prefix}{self.title} {self._quality_dot()}</span>'
            f'<span class="kpi-value">{self._format_value()}{self.unit}</span>'
            f'<span class="kpi-delta">{delta_str}</span>'
            f"</div>"
        )

    def render(self) -> None:  # pragma: no cover
        import streamlit as st

        delta_color: str
        if self.delta is None:
            delta_val = None
            delta_color = "normal"
        else:
            delta_color = "normal" if self.delta >= 0 else "inverse"
            delta_str = f"{self.delta:+.1f}%"
            if self.delta_label:
                delta_str += f" {self.delta_label}"
            delta_val = delta_str  # type: ignore[assignment]

        label = f"{self.icon} {self.title}" if self.icon else self.title
        label += f" {self._quality_dot()}"

        st.metric(
            label=label,
            value=f"{self._format_value()}{self.unit}",
            delta=delta_val,
            delta_color=delta_color,
            help=self.tooltip or None,
        )


def _build_kpi_html(
    tokens: DesignTokens,
    label: str,
    value: str,
    delta: str | None = None,
    delta_color: str | None = None,
) -> str:
    """Build the HTML for a KPI card. Pure function (testable)."""
    c = tokens.colors
    delta_html = ""
    if delta is not None:
        color = delta_color or c.text_secondary
        delta_html = (
            f'<div style="color: {color}; font-size: '
            f'{tokens.typography.font_size_sm};">{delta}</div>'
        )
    return (
        '<div class="market-ai-kpi-card">'
        f'<div class="market-ai-kpi-label">{label}</div>'
        f'<div class="market-ai-kpi-value">{value}</div>'
        f"{delta_html}"
        "</div>"
    )


def render_kpi_card(
    tokens: DesignTokens,
    label: str,
    value: float | str,
    delta: float | None = None,
    fmt: str = "number_decimal",
) -> None:  # pragma: no cover
    """Render a single KPI card.

    Args:
        tokens: DESIGN_TOKENS from ``load_design_tokens()``.
        label: Label shown above the value.
        value: Numeric or string value to display.
        delta: Optional delta (signed) shown below value.
        fmt: Format string name from tokens.formats (e.g. ``percent``).
    """
    # Format the value via tokens.formats (Rule 20: no hardcoded format strings)
    if isinstance(value, (int, float)):
        fmt_template = getattr(tokens.formats, fmt, "{value:,.2f}")
        value_str = fmt_template.format(value=value)
    else:
        value_str = str(value)

    delta_str = None
    delta_color = None
    if delta is not None:
        delta_str = tokens.formats.percent_signed.format(value=delta)
        delta_color = tokens.colors.for_pnl(delta)

    html = _build_kpi_html(tokens, label, value_str, delta_str, delta_color)

    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso
    import streamlit as st  # pragma: no cover
    st.markdown(html, unsafe_allow_html=True)


def render_kpi_row(tokens: DesignTokens, kpis: list[dict[str, object]]) -> None:  # pragma: no cover
    """Render a horizontal row of KPI cards.

    Each dict must include 'label' and 'value'; optional 'delta' and 'fmt'.
    """
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso
    import streamlit as st  # pragma: no cover

    cols = st.columns(len(kpis))
    for col, kpi in zip(cols, kpis, strict=True):
        with col:
            render_kpi_card(
                tokens=tokens,
                label=str(kpi["label"]),
                value=kpi["value"],  # type: ignore[arg-type]
                delta=kpi.get("delta"),  # type: ignore[arg-type]
                fmt=str(kpi.get("fmt", "number_decimal")),
            )
