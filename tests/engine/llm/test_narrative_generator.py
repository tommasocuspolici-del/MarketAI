"""Tests — NarrativeGenerator (Fase 9)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from engine.llm.narrative_generator import NarrativeGenerator


class TestNarrativeGenerator:
    def _gen(self) -> NarrativeGenerator:
        return NarrativeGenerator()

    def test_generate_market_narrative_returns_string(self) -> None:
        gen = self._gen()
        with patch("shared.feature_flags.is_enabled", return_value=False):
            result = gen.generate_market_narrative({"regime": "bull", "vix": 18.0})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_bull_regime_mentioned(self) -> None:
        gen = self._gen()
        with patch("shared.feature_flags.is_enabled", return_value=False):
            result = gen.generate_market_narrative({"regime": "bull"})
        assert "rialzista" in result.lower()

    def test_bear_regime_mentioned(self) -> None:
        gen = self._gen()
        with patch("shared.feature_flags.is_enabled", return_value=False):
            result = gen.generate_market_narrative({"regime": "bear"})
        assert "ribassista" in result.lower()

    def test_high_vix_mentioned(self) -> None:
        gen = self._gen()
        with patch("shared.feature_flags.is_enabled", return_value=False):
            result = gen.generate_market_narrative({"vix": 35.0})
        assert "35" in result or "elevata" in result

    def test_low_vix_mentioned(self) -> None:
        gen = self._gen()
        with patch("shared.feature_flags.is_enabled", return_value=False):
            result = gen.generate_market_narrative({"vix": 12.0})
        assert "12" in result or "contenuta" in result

    def test_positive_composite_score(self) -> None:
        gen = self._gen()
        with patch("shared.feature_flags.is_enabled", return_value=False):
            result = gen.generate_market_narrative({"composite_score": 0.5})
        assert "positivo" in result.lower() or "0.50" in result

    def test_negative_composite_score(self) -> None:
        gen = self._gen()
        with patch("shared.feature_flags.is_enabled", return_value=False):
            result = gen.generate_market_narrative({"composite_score": -0.5})
        assert "negativo" in result.lower() or "-0.50" in result

    def test_empty_context_no_crash(self) -> None:
        gen = self._gen()
        with patch("shared.feature_flags.is_enabled", return_value=False):
            result = gen.generate_market_narrative({})
        assert isinstance(result, str)

    def test_generate_portfolio_comment_returns_string(self) -> None:
        gen = self._gen()
        with patch("shared.feature_flags.is_enabled", return_value=False):
            result = gen.generate_portfolio_comment({
                "total_value": 50000.0, "pnl_pct": 3.5,
            })
        assert isinstance(result, str)
        assert len(result) > 0

    def test_portfolio_total_value_in_output(self) -> None:
        gen = self._gen()
        with patch("shared.feature_flags.is_enabled", return_value=False):
            result = gen.generate_portfolio_comment({"total_value": 75000.0, "pnl_pct": 2.0})
        assert "75" in result  # 75,000 o 75000

    def test_portfolio_pnl_in_output(self) -> None:
        gen = self._gen()
        with patch("shared.feature_flags.is_enabled", return_value=False):
            result = gen.generate_portfolio_comment({"total_value": 50000.0, "pnl_pct": -1.5})
        assert "-1.50" in result or "1.5" in result

    def test_template_disabled_label_present(self) -> None:
        gen = self._gen()
        with patch("shared.feature_flags.is_enabled", return_value=False):
            result = gen.generate_market_narrative({})
        assert "DISABLED" in result or "Template" in result

    def test_llm_path_calls_gateway(self) -> None:
        gen = self._gen()
        from shared.llm.llm_gateway import LLMResult, LLMStatus
        mock_result = LLMResult(
            text="LLM generated narrative",
            source="llm",
            model="mistral:7b-q4",
            latency_ms=500.0,
            cached=False,
        )
        with patch("shared.feature_flags.is_enabled", return_value=True):
            with patch.object(gen._llm, "is_available", return_value=True):
                with patch.object(gen._llm, "generate", return_value=mock_result) as mock_gen:
                    result = gen.generate_market_narrative({"regime": "bull"})
        assert result == "LLM generated narrative"
        mock_gen.assert_called_once()
