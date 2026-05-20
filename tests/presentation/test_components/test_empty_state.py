"""Tests for EmptyState component — to_html() only (no Streamlit)."""
from __future__ import annotations

import pytest

from presentation.ui.components.empty_state import EmptyState


class TestEmptyStateHtml:
    def test_title_in_html(self) -> None:
        html = EmptyState("Portfolio vuoto").to_html()
        assert "Portfolio vuoto" in html

    def test_hint_in_html_when_provided(self) -> None:
        html = EmptyState("Test", hint="Importa i dati").to_html()
        assert "Importa i dati" in html

    def test_hint_absent_when_empty(self) -> None:
        html = EmptyState("Test").to_html()
        assert "<p></p>" not in html

    @pytest.mark.parametrize("severity", ["info", "warning", "error", "loading"])
    def test_severity_in_class(self, severity: str) -> None:
        html = EmptyState("Test", severity=severity).to_html()
        assert f"severity-{severity}" in html

    def test_icon_override(self) -> None:
        html = EmptyState("Test", icon="🚀").to_html()
        assert "🚀" in html

    def test_default_icon_info(self) -> None:
        html = EmptyState("Test", severity="info").to_html()
        assert "ℹ️" in html

    def test_default_icon_error(self) -> None:
        html = EmptyState("Test", severity="error").to_html()
        assert "❌" in html

    def test_default_icon_loading(self) -> None:
        html = EmptyState("Test", severity="loading").to_html()
        assert "⏳" in html


class TestEmptyStateDefaults:
    def test_default_severity_is_info(self) -> None:
        state = EmptyState("Test")
        assert state.severity == "info"

    def test_default_hint_is_empty(self) -> None:
        state = EmptyState("Test")
        assert state.hint == ""

    def test_default_icon_is_empty(self) -> None:
        state = EmptyState("Test")
        assert state.icon == ""
