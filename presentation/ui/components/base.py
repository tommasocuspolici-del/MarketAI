"""base — BaseComponent ABC for all UI components.

Every new component inherits from this class:
  · ``render()``   — Streamlit output (pragma: no cover)
  · ``to_html()``  — Pure HTML string, testable without Streamlit

Test pattern::

    comp = KpiCard("Value", 1234.5, unit="€")
    assert "1,235" in comp.to_html()     # testable without Streamlit
    assert "€" in comp.to_html()
"""
from __future__ import annotations

from abc import ABC, abstractmethod

__all__ = ["BaseComponent"]


class BaseComponent(ABC):
    """Abstract base for all MarketAI UI components."""

    @abstractmethod
    def to_html(self) -> str:
        """Return a pure HTML representation — no Streamlit dependency."""
        ...

    @abstractmethod
    def render(self) -> None:
        """Render the component in the current Streamlit context.

        Always mark implementations with ``# pragma: no cover``.
        """
        ...
