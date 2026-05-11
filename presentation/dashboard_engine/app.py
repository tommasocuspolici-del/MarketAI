"""Dashboard Engine — main entry point.

Run with:  streamlit run presentation/dashboard_engine/app.py

Streamlit auto-discovers pages from the ``pages/`` folder. This script
is the landing page (home) that points users to the available analysis
modules.
"""
from __future__ import annotations

from presentation.dashboard_engine.pages.E1_Market_Overview import body_market_overview
from presentation.ui.page_factory import render_page

__version__ = "6.0.0"


def main() -> None:
    """Entry point — same as E1 (Market Overview)."""
    render_page("Market Overview", "📊", body_market_overview)


if __name__ == "__main__":   # pragma: no cover
    main()
