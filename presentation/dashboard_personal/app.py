"""Dashboard Personal — main entry point.

Run with:  streamlit run presentation/dashboard_personal/app.py
"""
from __future__ import annotations

from presentation.dashboard_personal.pages.P1_Overview_Patrimonio import (
    body_overview_patrimonio,
)
from presentation.ui.page_factory import render_page

__version__ = "6.0.0"


def main() -> None:
    render_page("Overview Patrimonio", "💼", body_overview_patrimonio)


if __name__ == "__main__":   # pragma: no cover
    main()
