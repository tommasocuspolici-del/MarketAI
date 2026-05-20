"""ic_breakdown_bar — ICBreakdownBar component for K1 signal breakdown.

Shows the 7 composite components with value, IC, and quality flag.

Example::

    bar = ICBreakdownBar(
        signals={"Technical": (0.42, 0.08, "ok"), "Macro": (0.28, 0.11, "ok")},
        composite_value=0.34,
    )
    assert "Technical" in bar.to_html()
    bar.render()  # pragma: no cover
"""
from __future__ import annotations

from dataclasses import dataclass, field

from presentation.ui.components.base import BaseComponent
from presentation.ui.design_tokens import TOKENS

__all__ = ["ICBreakdownBar"]


@dataclass
class ICBreakdownBar(BaseComponent):
    """Horizontal bar chart of composite-signal components.

    Args:
        signals:         ``{name: (value, ic_estimate, quality_flag)}``
                         where value ∈ [-1, 1].
        composite_value: Final composite signal value.
        regime:          Current market regime (used in chart title).
    """

    signals: dict[str, tuple[float, float | None, str]] = field(default_factory=dict)
    composite_value: float = 0.0
    regime: str = "transition"

    def to_html(self) -> str:
        """Return a simple HTML table — testable without Streamlit."""
        if not self.signals:
            return '<div class="ic-breakdown-empty">Nessun segnale</div>'
        rows = []
        for name, (val, ic, flag) in self.signals.items():
            ic_str = f"IC: {ic:.3f}" if ic is not None else "IC: —"
            bar_pct = int((val + 1) / 2 * 100)   # map [-1,1] → [0,100]
            color = TOKENS.colors.signal_color(val)
            rows.append(
                f"<tr>"
                f'<td style="width:120px">{name}</td>'
                f"<td>{val:+.3f}</td>"
                f'<td><div style="width:{bar_pct}%;background:{color};height:8px"></div></td>'
                f"<td>{ic_str}</td>"
                f"<td>{flag}</td>"
                f"</tr>"
            )
        composite_row = (
            f'<tr style="font-weight:bold">'
            f"<td>COMPOSITO</td>"
            f"<td>{self.composite_value:+.3f}</td>"
            f"<td></td><td></td>"
            f"<td>{self.regime.upper()}</td>"
            f"</tr>"
        )
        return f"<table>{''.join(rows)}{composite_row}</table>"

    def render(self) -> None:  # pragma: no cover
        import streamlit as st
        from presentation.ui.chart_theme import ChartFactory

        if not self.signals:
            st.info("Nessun segnale disponibile nel registry.")
            return

        chart_signals = {name: (val, ic) for name, (val, ic, _) in self.signals.items()}
        fig = ChartFactory.signal_breakdown(
            chart_signals,
            regime=self.regime,
            title=f"Composite Signal — 7 Componenti (regime: {self.regime.upper()})",
        )
        st.plotly_chart(fig, use_container_width=True)
