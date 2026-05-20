"""Tests for StatusDot component — to_html() only (no Streamlit)."""
from __future__ import annotations

import pytest

from presentation.ui.components.status_dot import StatusDot


class TestStatusDotHtml:
    def test_label_in_html(self) -> None:
        html = StatusDot("Database").to_html()
        assert "Database" in html

    @pytest.mark.parametrize("status,dot", [
        ("ok",       "🟢"),
        ("degraded", "🟡"),
        ("error",    "🔴"),
        ("unknown",  "⚪"),
    ])
    def test_dot_symbol_for_status(self, status: str, dot: str) -> None:
        html = StatusDot("Test", status=status).to_html()
        assert dot in html

    def test_detail_as_tooltip(self) -> None:
        html = StatusDot("FRED API", detail="rate limit hit").to_html()
        assert 'title="rate limit hit"' in html

    def test_last_update_in_html(self) -> None:
        html = StatusDot("DB", last_update="14:30").to_html()
        assert "14:30" in html

    def test_no_tooltip_when_no_detail(self) -> None:
        html = StatusDot("Test").to_html()
        assert "title=" not in html

    def test_unknown_status_defaults_to_white(self) -> None:
        dot = StatusDot("X", status="bogus")
        assert dot.dot == "⚪"


class TestStatusDotDefaults:
    def test_default_status_is_unknown(self) -> None:
        assert StatusDot("Test").status == "unknown"

    def test_default_detail_is_empty(self) -> None:
        assert StatusDot("Test").detail == ""
