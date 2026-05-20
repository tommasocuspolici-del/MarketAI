"""status_dot — StatusDot component for system health indicators.

Used in S0 Health Monitor tabs to show per-source status at a glance.

Example::

    dot = StatusDot("Database", status="ok", detail="DuckDB v1.2.1")
    assert "🟢" in dot.to_html()
    dot.render()  # pragma: no cover
"""
from __future__ import annotations

from dataclasses import dataclass

from presentation.ui.components.base import BaseComponent

__all__ = ["StatusDot"]

_DOT: dict[str, str] = {
    "ok":       "🟢",
    "degraded": "🟡",
    "error":    "🔴",
    "unknown":  "⚪",
}


@dataclass
class StatusDot(BaseComponent):
    """Traffic-light indicator with label, status, and optional tooltip.

    Args:
        label:       Display label (e.g. "FRED API").
        status:      "ok" | "degraded" | "error" | "unknown".
        detail:      Detail text shown as tooltip or subtitle.
        last_update: Timestamp of last successful check.
    """
    label: str
    status: str = "unknown"
    detail: str = ""
    last_update: str = ""

    @property
    def dot(self) -> str:
        return _DOT.get(self.status, "⚪")

    def to_html(self) -> str:
        tooltip = f' title="{self.detail}"' if self.detail else ""
        update = (
            f' <small style="opacity:0.6">({self.last_update})</small>'
            if self.last_update
            else ""
        )
        return (
            f'<span class="status-dot"{tooltip}>'
            f"{self.dot} {self.label}{update}"
            f"</span>"
        )

    def render(self) -> None:  # pragma: no cover
        import streamlit as st

        detail_str = f": {self.detail}" if self.detail else ""
        update_str = f" ({self.last_update})" if self.last_update else ""
        st.markdown(
            f"{self.dot} **{self.label}**{detail_str}{update_str}",
            help=self.detail or None,
        )
