"""KPI card component — labeled metric tile."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "6.0.0"

__all__ = ["render_kpi_card", "render_kpi_row"]


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
