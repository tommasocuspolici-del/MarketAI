"""sidebar_nav — Hierarchical sidebar navigation with fuzzy search.

Replaces the flat navigation list with a grouped, collapsible sidebar that
includes a real-time search filter and a system-status pill at the bottom.

Usage (in the main app entry point)::

    from presentation.ui.sidebar_nav import SidebarNavigator
    SidebarNavigator().render()

Groups:
    Dashboard → Mercato → Analisi Avanzata → Portfolio → Intelligence → Sistema
"""
from __future__ import annotations

from dataclasses import dataclass, field

from presentation.ui.session_keys import SK
from presentation.ui.design_tokens import TOKENS

__all__ = ["NavGroup", "NavPage", "NAV_STRUCTURE", "SidebarNavigator"]


@dataclass
class NavPage:
    """A single navigation entry."""
    id: str
    label: str
    icon: str           # Tabler icon name, e.g. "ti-chart-line"
    page_file: str      # Page filename (without .py) in pages/
    is_stub: bool = False
    badge: str | None = None


@dataclass
class NavGroup:
    """A collapsible group of navigation entries."""
    id: str
    label: str
    icon: str
    pages: list[NavPage] = field(default_factory=list)
    expanded_by_default: bool = False


NAV_STRUCTURE: list[NavGroup | NavPage] = [
    NavPage("dashboard", "Dashboard", "ti-layout-dashboard", "K1_Composite_Signal"),

    NavGroup("mercato", "Mercato", "ti-chart-line", expanded_by_default=True, pages=[
        NavPage("e1", "Market Overview",    "ti-eye",            "E1_Market_Overview"),
        NavPage("m1", "Macro Conviction",   "ti-world",          "M1_Macro_Signals"),
        NavPage("m2", "VIX & Volatility",   "ti-wave-saw-tool",  "M2_VIX_Signals"),
        NavPage("m3", "Labour Market",      "ti-users",          "M3_Labour_Market"),
        NavPage("m4", "Yield Curve",        "ti-chart-dots",     "M4_Yield_Curve"),
        NavPage("m5", "Economic Surprise",  "ti-bolt",           "M5_Economic_Surprise"),
        NavPage("m6", "Valuation P/E",      "ti-calculator",     "M6_Valuation_PE"),
    ]),

    NavGroup("analytics", "Analisi Avanzata", "ti-math-function", pages=[
        NavPage("q1",  "Backtesting",        "ti-player-play",     "Q1_Backtesting"),
        NavPage("q2",  "Stress Test",        "ti-alert-triangle",  "Q2_Stress_Test"),
        NavPage("q3",  "Correlazioni",       "ti-arrows-split",    "Q3_Correlations"),
        NavPage("q4",  "Portfolio Optimizer","ti-adjustments",     "Q4_Optimizer"),
        NavPage("q5",  "Sentiment Analysis", "ti-mood-happy",      "Q5_Sentiment"),
        NavPage("q11", "Options Analytics",  "ti-currency-dollar", "Q11_Options"),
        NavPage("q12", "Multi-Timeframe",    "ti-clock",           "Q12_MultiTimeframe"),
        NavPage("q14", "Strategy Lab",       "ti-flask",           "Q14_Strategy_Lab"),
    ]),

    NavGroup("portfolio", "Portfolio", "ti-briefcase", pages=[
        NavPage("p1",  "Panoramica",          "ti-home",   "P1_Overview"),
        NavPage("p2",  "Posizioni eToro",     "ti-table",  "P2_Portafoglio_eToro"),
        NavPage("p3",  "Import Manuale",      "ti-upload", "P3_Manual_Entry"),
        NavPage("p4",  "Profilo Investitore", "ti-user",   "P4_Investor_Profile"),
        NavPage("p5",  "Risk Analysis",       "ti-shield", "P5_Risk_Analysis"),
        NavPage("p10", "Obiettivi",           "ti-target", "P10_Goals"),
    ]),

    NavGroup("intelligence", "Intelligence", "ti-brain", pages=[
        NavPage("n1", "News Feed",       "ti-news",          "N1_News_Feed",
                is_stub=True, badge="Fase 6"),
        NavPage("n2", "News Analysis",   "ti-chart-pie",     "N2_News_Analysis",
                is_stub=True, badge="Fase 6"),
        NavPage("m7", "IB Forecast",     "ti-building-bank", "M7_IB_Consensus",
                is_stub=True, badge="Fase 8"),
        NavPage("a1", "Market Q&A",      "ti-message-dots",  "A1_Market_QA",
                is_stub=True, badge="Fase 7"),
        NavPage("c1", "Custom Indicators","ti-tools",        "C1_Custom_Indicators"),
    ]),

    NavGroup("sistema", "Sistema", "ti-settings", pages=[
        NavPage("s0", "Health Monitor", "ti-activity",    "S0_Health"),
        NavPage("s2", "Impostazioni",   "ti-adjustments", "S2_Settings"),
    ]),
]


class SidebarNavigator:
    """Renders the hierarchical sidebar navigation in Streamlit."""

    def render(self) -> None:  # pragma: no cover
        import streamlit as st

        status_color, status_label = self._system_status()

        # Fuzzy search input
        query: str = st.sidebar.text_input(
            "",
            placeholder="🔍 Cerca pagina...",
            key=SK.SIDEBAR_SEARCH,
            label_visibility="collapsed",
        )

        for item in NAV_STRUCTURE:
            if isinstance(item, NavPage):
                self._render_page_link(item, query)
            else:
                self._render_group(item, query)

        # System status pill
        st.sidebar.markdown("---")
        st.sidebar.markdown(
            f'<div style="font-size:12px;color:{status_color};text-align:center">'
            f"● {status_label}"
            f"</div>",
            unsafe_allow_html=True,
        )

    def _render_group(self, group: NavGroup, query: str) -> None:  # pragma: no cover
        import streamlit as st

        matching = [p for p in group.pages if self._matches(p, query)]
        if not matching:
            return

        key = f"{SK.SIDEBAR_EXPANDED_PREFIX}{group.id}"
        with st.sidebar.expander(
            group.label,
            expanded=st.session_state.get(key, group.expanded_by_default),
        ):
            for page in matching:
                self._render_page_link(page, query)

    @staticmethod
    def _render_page_link(page: NavPage, query: str) -> None:  # pragma: no cover
        import streamlit as st

        if not SidebarNavigator._matches(page, query):
            return

        label = page.label
        if page.is_stub and page.badge:
            label = f"{label} · _{page.badge}_"

        try:
            st.sidebar.page_link(
                f"pages/{page.page_file}.py",
                label=label,
            )
        except Exception:
            st.sidebar.markdown(f"· {label}")

    @staticmethod
    def _matches(page: NavPage, query: str) -> bool:
        """Return True if the page label contains the query (case-insensitive)."""
        return not query or query.lower() in page.label.lower()

    @staticmethod
    def _system_status() -> tuple[str, str]:  # pragma: no cover
        """Return (color, label) for the system status pill."""
        try:
            from shared.monitoring.system_status import get_system_status
            status = get_system_status()
        except Exception:
            status = "UNKNOWN"

        mapping = {
            "OPERATIONAL": (TOKENS.colors.health_operational, "Operational"),
            "DEGRADED":    (TOKENS.colors.health_degraded,    "Degraded"),
            "DOWN":        (TOKENS.colors.health_down,        "Down"),
        }
        return mapping.get(status, (TOKENS.colors.text_muted, status.title()))
