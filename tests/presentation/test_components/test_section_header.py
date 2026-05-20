"""Tests for SectionHeader component — to_html() only (no Streamlit)."""
from __future__ import annotations

from presentation.ui.components.section_header import SectionHeader


class TestSectionHeaderHtml:
    def test_title_in_html(self) -> None:
        html = SectionHeader(title="Market Overview").to_html()
        assert "Market Overview" in html

    def test_icon_in_html(self) -> None:
        html = SectionHeader(title="Test", icon="📊").to_html()
        assert "📊" in html

    def test_subtitle_in_html_when_provided(self) -> None:
        html = SectionHeader(title="T", subtitle="Dati aggiornati ogni 5m").to_html()
        assert "Dati aggiornati ogni 5m" in html

    def test_subtitle_absent_when_empty(self) -> None:
        html = SectionHeader(title="T").to_html()
        assert "<p></p>" not in html

    def test_ttl_shown_when_nonzero(self) -> None:
        html = SectionHeader(title="T", ttl=300).to_html()
        assert "300" in html

    def test_ttl_absent_when_zero(self) -> None:
        html = SectionHeader(title="T", ttl=0).to_html()
        assert "aggiornato ogni" not in html

    def test_default_icon(self) -> None:
        html = SectionHeader(title="T").to_html()
        assert "📊" in html
