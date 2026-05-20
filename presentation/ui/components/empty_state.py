"""empty_state — EmptyState component for empty/loading/error states.

Provides a consistent look for all non-data UI states across the dashboard.

Example::

    EmptyState(
        "Portfolio vuoto",
        hint="Importa le posizioni dalla tab Import",
        severity="info",
    ).render()

    assert "severity-info" in EmptyState("Test", severity="info").to_html()
"""
from __future__ import annotations

from dataclasses import dataclass

from presentation.ui.components.base import BaseComponent

__all__ = ["EmptyState"]

_ICONS: dict[str, str] = {
    "info":    "ℹ️",
    "warning": "⚠️",
    "error":   "❌",
    "loading": "⏳",
}


@dataclass
class EmptyState(BaseComponent):
    """Unified component for empty, loading, and error states.

    Args:
        title:    Short state title (e.g. "Nessun dato disponibile").
        hint:     Action hint for the user.
        severity: "info" | "warning" | "error" | "loading".
        icon:     Optional icon override (emoji or text).
    """
    title: str
    hint: str = ""
    severity: str = "info"
    icon: str = ""

    def to_html(self) -> str:
        icon = self.icon or _ICONS.get(self.severity, "ℹ️")
        hint_html = f"<p>{self.hint}</p>" if self.hint else ""
        return (
            f'<div class="empty-state severity-{self.severity}">'
            f"<span>{icon}</span>"
            f"<h3>{self.title}</h3>"
            f"{hint_html}"
            f"</div>"
        )

    def render(self) -> None:  # pragma: no cover
        import streamlit as st

        msg = f"**{self.title}**"
        if self.hint:
            msg += f"\n\n{self.hint}"

        handlers = {
            "info":    st.info,
            "warning": st.warning,
            "error":   st.error,
            "loading": lambda m: st.info(f"⏳ {m}"),
        }
        handlers.get(self.severity, st.info)(msg)
