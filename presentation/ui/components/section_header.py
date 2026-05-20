"""section_header — SectionHeader component for consistent page titles.

Used by the page_layout decorator and directly in page bodies.

Example::

    sh = SectionHeader(title="Market Overview", icon="📊")
    assert "Market Overview" in sh.to_html()
    sh.render()  # pragma: no cover
"""
from __future__ import annotations

from dataclasses import dataclass

from presentation.ui.components.base import BaseComponent

__all__ = ["SectionHeader"]


@dataclass
class SectionHeader(BaseComponent):
    """Page section header with icon, title, and optional timestamp.

    Args:
        title:      Section title.
        icon:       Emoji icon prefix.
        subtitle:   Optional subtitle rendered as a caption.
        ttl:        Cache TTL in seconds (shown as "aggiornato ogni Xs").
    """
    title: str
    icon: str = "📊"
    subtitle: str = ""
    ttl: int = 0

    def to_html(self) -> str:
        sub = f"<p>{self.subtitle}</p>" if self.subtitle else ""
        ttl_str = (
            f"<small>aggiornato ogni {self.ttl}s</small>" if self.ttl else ""
        )
        return (
            f'<div class="section-header">'
            f"<h2>{self.icon} {self.title} {ttl_str}</h2>"
            f"{sub}"
            f"</div>"
        )

    def render(self) -> None:  # pragma: no cover
        import streamlit as st

        st.markdown(f"## {self.icon} {self.title}")
        if self.subtitle:
            st.caption(self.subtitle)
        if self.ttl:
            st.caption(f"Aggiornato ogni {self.ttl}s")
