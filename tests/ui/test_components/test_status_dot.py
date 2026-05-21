"""Tests for StatusDot component."""
from __future__ import annotations
import pytest
from presentation.ui.components.status_dot import StatusDot


class TestStatusDotHtml:
    @pytest.mark.parametrize("status,dot", [
        ("ok",       "🟢"),
        ("degraded", "🟡"),
        ("error",    "🔴"),
        ("unknown",  "⚪"),
    ])
    def test_correct_dot_per_status(self, status: str, dot: str) -> None:
        sd = StatusDot(label="Test", status=status)
        assert dot in sd.to_html()

    def test_label_in_html(self) -> None:
        sd = StatusDot(label="FRED API", status="ok")
        assert "FRED API" in sd.to_html()

    def test_detail_in_title_attr(self) -> None:
        sd = StatusDot(label="DB", status="ok", detail="DuckDB 1.2MB")
        html = sd.to_html()
        assert "DuckDB 1.2MB" in html

    def test_unknown_status_falls_back_to_grey(self) -> None:
        sd = StatusDot(label="X", status="nonexistent")
        assert "⚪" in sd.to_html()

    def test_returns_string(self) -> None:
        sd = StatusDot(label="X", status="ok")
        assert isinstance(sd.to_html(), str)

    def test_last_update_present(self) -> None:
        sd = StatusDot(label="X", status="ok", last_update="2026-05-21 10:00")
        html = sd.to_html()
        assert isinstance(html, str)

    def test_defaults(self) -> None:
        sd = StatusDot(label="X")
        assert sd.status == "unknown"
        assert sd.detail == ""
        assert sd.last_update == ""
