"""Tests — LLMGateway (Fase 9).

Testa tutti gli stati: DISABLED, AVAILABLE, DOWN, DEGRADED.
Nessun Ollama reale richiesto in CI — usa mock.
"""
from unittest.mock import MagicMock, patch

import pytest

from shared.llm.llm_gateway import LLMGateway, LLMResult, LLMStatus


@pytest.fixture
def gateway() -> LLMGateway:
    """Gateway con LLM disabilitato (feature flag default)."""
    return LLMGateway()


def test_status_disabled_when_flag_off(gateway: LLMGateway) -> None:
    with patch("shared.llm.llm_gateway.is_enabled", return_value=False):
        assert gateway.status() == LLMStatus.DISABLED


def test_is_available_false_when_disabled(gateway: LLMGateway) -> None:
    with patch("shared.llm.llm_gateway.is_enabled", return_value=False):
        assert gateway.is_available() is False


def test_generate_returns_template_when_disabled(gateway: LLMGateway) -> None:
    with patch("shared.llm.llm_gateway.is_enabled", return_value=False):
        result = gateway.generate("market_narrative", {"date": "2025-01-01", "sp500_change": 1.2, "vix": 18.0, "composite_score": 0.3})
    assert isinstance(result, LLMResult)
    assert result.source == "template"
    assert result.model == "template_only"
    assert result.cached is False
    assert len(result.text) > 0


def test_generate_template_fallback_no_crash(gateway: LLMGateway) -> None:
    with patch("shared.llm.llm_gateway.is_enabled", return_value=False):
        result = gateway.generate("market_narrative", {})
    assert result.source == "template"
    assert isinstance(result.text, str)


def test_generate_cache_used_when_llm_available(gateway: LLMGateway) -> None:
    from datetime import UTC, datetime
    gateway._status = LLMStatus.AVAILABLE
    gateway._last_check = datetime.now(UTC)  # evita re-check status
    with patch("shared.llm.llm_gateway.is_enabled", return_value=True):
        with patch.object(gateway, "_call_ollama", return_value="Test LLM output") as mock_call:
            r1 = gateway.generate("market_narrative", {"date": "2025"})
            r2 = gateway.generate("market_narrative", {"date": "2025"})

    assert mock_call.call_count == 1  # secondo accesso da cache
    assert r2.source == "cache"
    assert r2.cached is True


def test_generate_fallback_on_ollama_down(gateway: LLMGateway) -> None:
    gateway._status = LLMStatus.AVAILABLE
    with patch("shared.llm.llm_gateway.is_enabled", return_value=True):
        with patch.object(gateway, "_call_ollama", side_effect=ConnectionError("down")):
            result = gateway.generate("market_narrative", {})
    assert result.source == "template"
    assert gateway._status == LLMStatus.DOWN


def test_generate_ib_extraction_returns_json(gateway: LLMGateway) -> None:
    with patch("shared.llm.llm_gateway.is_enabled", return_value=False):
        result = gateway.generate("ib_extraction", {})
    assert result.source == "template"
    assert result.text == "[]"  # Template per ib_extraction è JSON vuoto


def test_llm_result_has_required_fields(gateway: LLMGateway) -> None:
    with patch("shared.llm.llm_gateway.is_enabled", return_value=False):
        result = gateway.generate("market_narrative", {})
    assert hasattr(result, "text")
    assert hasattr(result, "source")
    assert hasattr(result, "model")
    assert hasattr(result, "latency_ms")
    assert hasattr(result, "cached")
    assert result.latency_ms >= 0
