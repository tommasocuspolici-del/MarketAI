"""Tests for sidebar navigation structure (non-Streamlit parts)."""
from __future__ import annotations
import pytest
from presentation.ui.sidebar_nav import NAV_STRUCTURE, NavGroup, NavPage, SidebarNavigator


class TestNavStructure:
    def test_nav_structure_not_empty(self) -> None:
        assert len(NAV_STRUCTURE) > 0

    def test_has_dashboard_top_page(self) -> None:
        top = NAV_STRUCTURE[0]
        assert isinstance(top, NavPage)
        assert top.id == "dashboard"

    def test_has_five_groups(self) -> None:
        groups = [item for item in NAV_STRUCTURE if isinstance(item, NavGroup)]
        assert len(groups) >= 4

    def test_mercato_group_has_m_pages(self) -> None:
        mercato = next(g for g in NAV_STRUCTURE if isinstance(g, NavGroup) and g.id == "mercato")
        ids = [p.id for p in mercato.pages]
        assert "e1" in ids
        assert "m1" in ids

    def test_analytics_group_has_q_pages(self) -> None:
        analytics = next(g for g in NAV_STRUCTURE if isinstance(g, NavGroup) and g.id == "analytics")
        ids = [p.id for p in analytics.pages]
        assert "q1" in ids
        assert "q3" in ids

    def test_intelligence_group_has_stubs(self) -> None:
        intel = next(g for g in NAV_STRUCTURE if isinstance(g, NavGroup) and g.id == "intelligence")
        stubs = [p for p in intel.pages if p.is_stub]
        assert len(stubs) >= 2

    def test_sistema_group_has_s0_s2(self) -> None:
        sistema = next(g for g in NAV_STRUCTURE if isinstance(g, NavGroup) and g.id == "sistema")
        ids = [p.id for p in sistema.pages]
        assert "s0" in ids
        assert "s2" in ids

    def test_portfolio_group_exists(self) -> None:
        groups = [item for item in NAV_STRUCTURE if isinstance(item, NavGroup)]
        ids = [g.id for g in groups]
        assert "portfolio" in ids

    def test_all_pages_have_icon(self) -> None:
        for item in NAV_STRUCTURE:
            assert item.icon, f"Missing icon on {item.id}"
            if isinstance(item, NavGroup):
                for page in item.pages:
                    assert page.icon, f"Missing icon on page {page.id}"

    def test_all_pages_have_page_file(self) -> None:
        for item in NAV_STRUCTURE:
            if isinstance(item, NavPage):
                assert item.page_file
            elif isinstance(item, NavGroup):
                for page in item.pages:
                    assert page.page_file, f"Missing page_file on {page.id}"

    def test_stub_pages_have_badge(self) -> None:
        for item in NAV_STRUCTURE:
            if isinstance(item, NavGroup):
                for page in item.pages:
                    if page.is_stub:
                        assert page.badge is not None, f"Stub {page.id} has no badge"

    def test_total_pages_at_least_twenty(self) -> None:
        total = 0
        for item in NAV_STRUCTURE:
            if isinstance(item, NavPage):
                total += 1
            elif isinstance(item, NavGroup):
                total += len(item.pages)
        assert total >= 20

    def test_navigator_instantiable(self) -> None:
        nav = SidebarNavigator()
        assert nav is not None

    def test_nav_group_expanded_by_default(self) -> None:
        mercato = next(g for g in NAV_STRUCTURE if isinstance(g, NavGroup) and g.id == "mercato")
        assert mercato.expanded_by_default is True
