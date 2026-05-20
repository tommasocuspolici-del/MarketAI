"""signal_badge — SignalBadge component for signal values in [-1, 1].

Used in K1 (7-component breakdown), E1 (signal sidebar), S0 (quality tab).

Example::

    badge = SignalBadge("Technical", 0.42, confidence=0.85, ic_estimate=0.07)
    assert "RIALZISTA" in badge.to_html()
    badge.render()  # pragma: no cover
"""
from __future__ import annotations

from dataclasses import dataclass

from presentation.ui.components.base import BaseComponent
from presentation.ui.design_tokens import TOKENS

__all__ = ["SignalBadge"]


@dataclass
class SignalBadge(BaseComponent):
    """Colored badge for a signal ∈ [-1, 1] with direction label and IC.

    Args:
        name:         Signal name (e.g. "Technical Composite").
        value:        Signal value in [-1, 1].
        confidence:   Confidence score in [0, 1]. Shown when < 0.9.
        ic_estimate:  Information Coefficient estimate. Shown when provided.
        quality_flag: Quality flag from AlphaDecayMonitor:
                      "ok" | "low_ic" | "insufficient_data" | "stale".
    """
    name: str
    value: float
    confidence: float = 1.0
    ic_estimate: float | None = None
    quality_flag: str = "ok"

    @property
    def direction(self) -> str:
        """Human-readable direction label for the signal value."""
        v = max(-1.0, min(1.0, float(self.value)))
        if v > 0.3:
            return "RIALZISTA"
        if v > 0.05:
            return "lieve ↑"
        if v > -0.05:
            return "NEUTRO"
        if v > -0.3:
            return "lieve ↓"
        return "RIBASSISTA"

    @property
    def color(self) -> str:
        return TOKENS.colors.signal_color(self.value)

    def to_html(self) -> str:
        ic_str = f" IC:{self.ic_estimate:.3f}" if self.ic_estimate is not None else ""
        return (
            f'<span class="signal-badge" style="color:{self.color}">'
            f"{self.name}: {self.value:+.3f} ({self.direction}){ic_str}"
            f"</span>"
        )

    def render(self) -> None:  # pragma: no cover
        import streamlit as st

        ic_str = (
            f" · IC {self.ic_estimate:.3f}" if self.ic_estimate is not None else ""
        )
        conf_str = (
            f" · conf. {self.confidence:.0%}" if self.confidence < 0.9 else ""
        )
        quality_icon = {
            "ok": "●",
            "low_ic": "◐",
            "insufficient_data": "○",
            "stale": "◌",
        }.get(self.quality_flag, "○")

        st.markdown(
            f'<div style="padding:6px 10px;border-radius:6px;'
            f"background:rgba(0,0,0,0.05);margin-bottom:4px\">"
            f'<span style="font-size:13px;color:{self.color}">'
            f"{quality_icon} <strong>{self.name}</strong>: "
            f"{self.value:+.3f} · {self.direction}{ic_str}{conf_str}"
            f"</span></div>",
            unsafe_allow_html=True,
        )
