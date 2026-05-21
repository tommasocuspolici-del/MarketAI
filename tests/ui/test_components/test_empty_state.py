"""Tests for EmptyState component."""
from __future__ import annotations
import pytest
from presentation.ui.components.empty_state import EmptyState


class TestEmptyStateHtml:
    def test_to_html_returns_string(self) -> None:
        es = EmptyState(title="Nessun dato")
        assert isinstance(es.to_html(), str)

    def test_to_html_contains_title(self) -> None:
        es = EmptyState(title="Nessun risultato")
        assert "Nessun risultato" in es.to_html()

    def test_to_html_contains_hint(self) -> None:
        es = EmptyState(title="Vuoto", hint="Importa i dati prima")
        assert "Importa i dati prima" in es.to_html()

    @pytest.mark.parametrize("severity", ["info", "warning", "error", "loading"])
    def test_to_html_severity_classes(self, severity: str) -> None:
        es = EmptyState(title="Test", severity=severity)
        html = es.to_html()
        assert severity in html

    def test_default_severity_is_info(self) -> None:
        es = EmptyState(title="Test")
        assert es.severity == "info"

    def test_custom_icon_used(self) -> None:
        es = EmptyState(title="Test", icon="🚀")
        assert "🚀" in es.to_html()

    def test_empty_hint_still_renders(self) -> None:
        es = EmptyState(title="No hint")
        html = es.to_html()
        assert "No hint" in html

    def test_error_severity(self) -> None:
        es = EmptyState(title="Errore DB", severity="error")
        html = es.to_html()
        assert "error" in html


class TestEmptyStateDefaults:
    def test_default_icon_empty(self) -> None:
        es = EmptyState(title="T")
        assert es.icon == ""

    def test_default_hint_empty(self) -> None:
        es = EmptyState(title="T")
        assert es.hint == ""
