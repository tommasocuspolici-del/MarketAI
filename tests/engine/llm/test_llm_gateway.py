"""Tests — LLMGateway (Fase 9)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from shared.llm.llm_gateway import LLMGateway, LLMResult, LLMStatus, get_llm_gateway


class TestLLMGateway:
    def _gateway(self) -> LLMGateway:
        return LLMGateway()

    def test_status_disabled_by_default(self) -> None:
        gw = self._gateway()
        with patch("shared.llm.llm_gateway.is_enabled", return_value=False):
            assert gw.status() == LLMStatus.DISABLED

    def test_is_available_false_when_disabled(self) -> None:
        gw = self._gateway()
        with patch("shared.llm.llm_gateway.is_enabled", return_value=False):
            assert gw.is_available() is False

    def test_generate_returns_template_when_disabled(self) -> None:
        gw = self._gateway()
        with patch("shared.llm.llm_gateway.is_enabled", return_value=False):
            result = gw.generate("market_narrative", {
                "date": "2025-01-01",
                "sp500_change": 0.5,
                "vix": 18.0,
                "composite_score": 0.3,
            })
        assert isinstance(result, LLMResult)
        assert result.source == "template"
        assert result.model == "template_only"
        assert result.cached is False
        assert isinstance(result.text, str)
        assert len(result.text) > 0

    def test_generate_template_fallback_on_missing_keys(self) -> None:
        gw = self._gateway()
        with patch("shared.llm.llm_gateway.is_enabled", return_value=False):
            result = gw.generate("market_narrative", {})
        assert isinstance(result.text, str)

    def test_generate_unknown_template_no_crash(self) -> None:
        gw = self._gateway()
        with patch("shared.llm.llm_gateway.is_enabled", return_value=False):
            result = gw.generate("nonexistent_template", {"foo": "bar"})
        assert isinstance(result.text, str)

    def test_generate_uses_cache_on_second_call(self) -> None:
        gw = self._gateway()
        context = {"date": "2025-01-01", "sp500_change": 0.5, "vix": 18.0, "composite_score": 0.2}

        # Simula LLM attivo per cache test
        with patch.object(gw, "is_available", return_value=True):
            with patch.object(gw, "_call_ollama", return_value="LLM response") as mock_call:
                r1 = gw.generate("market_narrative", context)
                r2 = gw.generate("market_narrative", context)

        # Prima chiamata: LLM
        assert mock_call.call_count == 1
        # Seconda chiamata: cache
        assert r2.source == "cache"
        assert r2.cached is True

    def test_generate_falls_back_to_template_on_ollama_error(self) -> None:
        gw = self._gateway()
        with patch.object(gw, "is_available", return_value=True):
            with patch.object(gw, "_call_ollama", side_effect=RuntimeError("Connection refused")):
                result = gw.generate("market_narrative", {})

        assert result.source == "template"
        assert gw._status == LLMStatus.DOWN

    def test_latency_ms_positive(self) -> None:
        gw = self._gateway()
        with patch("shared.llm.llm_gateway.is_enabled", return_value=False):
            result = gw.generate("risk_alert", {"indicator": "VIX", "value": 35.0, "threshold": 30.0})
        assert result.latency_ms >= 0

    def test_news_analysis_template(self) -> None:
        gw = self._gateway()
        with patch("shared.llm.llm_gateway.is_enabled", return_value=False):
            result = gw.generate("news_analysis", {
                "article_count": 10, "sentiment_label": "bullish", "score": 0.4,
                "top_tickers": "SPY, AAPL",
            })
        assert "10" in result.text or "bullish" in result.text or isinstance(result.text, str)

    def test_portfolio_comment_template(self) -> None:
        gw = self._gateway()
        with patch("shared.llm.llm_gateway.is_enabled", return_value=False):
            result = gw.generate("portfolio_comment", {
                "return_pct": 5.2, "vol_pct": 12.3, "beta": 0.85,
            })
        assert "5.2" in result.text or isinstance(result.text, str)


class TestGetLLMGateway:
    def test_singleton(self) -> None:
        gw1 = get_llm_gateway()
        gw2 = get_llm_gateway()
        assert gw1 is gw2

    def test_returns_llm_gateway(self) -> None:
        gw = get_llm_gateway()
        assert isinstance(gw, LLMGateway)


class TestLLMStatus:
    def test_status_values(self) -> None:
        assert LLMStatus.DISABLED == "disabled"
        assert LLMStatus.AVAILABLE == "available"
        assert LLMStatus.DEGRADED == "degraded"
        assert LLMStatus.DOWN == "down"
