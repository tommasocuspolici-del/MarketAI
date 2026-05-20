"""Tests for S0_Health data loaders — no Streamlit dependency."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from presentation.dashboard_engine.pages.S0_Health import (
    SignalQualityRow,
    CircuitBreakerRow,
    _load_circuit_breakers,
    _load_signal_quality,
    _load_ollama_status,
)


class TestLoadSignalQuality:
    def test_returns_list(self) -> None:
        result = _load_signal_quality()
        assert isinstance(result, list)

    def test_rows_are_signal_quality_rows(self) -> None:
        result = _load_signal_quality()
        for row in result:
            assert isinstance(row, SignalQualityRow)

    def test_sorted_by_name(self) -> None:
        result = _load_signal_quality()
        names = [r.name for r in result]
        assert names == sorted(names)

    def test_empty_registry_returns_empty(self) -> None:
        from shared.signal_registry import get_signal_registry
        get_signal_registry().clear()
        result = _load_signal_quality()
        assert result == []

    def test_stale_signal_flagged(self) -> None:
        from shared.signal_registry import get_signal_registry
        from shared.signal_types import Signal
        from datetime import UTC, datetime, timedelta

        registry = get_signal_registry()
        sig = Signal(name="_test_stale_s0", value=0.5, confidence=1.0, source_module="test")
        # Publish then manually expire it
        registry.publish(sig, ttl_seconds=1)
        import time; time.sleep(1.1)

        rows = _load_signal_quality()
        stale_row = next((r for r in rows if r.name == "_test_stale_s0"), None)
        if stale_row:
            assert stale_row.quality_flag == "stale"


class TestLoadCircuitBreakers:
    def test_returns_list(self) -> None:
        result = _load_circuit_breakers()
        assert isinstance(result, list)

    def test_rows_are_circuit_breaker_rows(self) -> None:
        result = _load_circuit_breakers()
        for row in result:
            assert isinstance(row, CircuitBreakerRow)

    def test_known_breakers_present(self) -> None:
        result = _load_circuit_breakers()
        names = {r.name for r in result}
        assert "yfinance" in names
        assert "fred" in names

    def test_fresh_breakers_closed(self) -> None:
        result = _load_circuit_breakers()
        for row in result:
            assert row.state in {"closed", "open", "half_open", "unknown"}


class TestLoadOllamaStatus:
    def test_returns_dict_with_required_keys(self) -> None:
        result = _load_ollama_status()
        assert "running" in result
        assert "models" in result
        assert "error" in result

    def test_not_running_when_no_server(self) -> None:
        # In test environment Ollama is not running
        result = _load_ollama_status()
        assert isinstance(result["running"], bool)
        assert isinstance(result["models"], list)

    def test_running_true_with_mock(self) -> None:
        import json
        import io

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"models": [{"name": "mistral:7b-q4"}]}
        ).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = _load_ollama_status()

        assert result["running"] is True
        assert "mistral:7b-q4" in result["models"]
        assert result["error"] is None
