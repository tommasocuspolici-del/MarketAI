"""Tests — engine.analytics.composite_signal_v3 (Fase 2).

Testa CompositeSignalAggregatorV3 dalla versione analytics
(distinct from engine.alpha_generation.composite_signal_v3).
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from engine.analytics.composite_signal_v3 import (
    CompositeSignalAggregatorV3,
    CompositeSignalOutputV3,
    _WEIGHTS_V3,
)


def _mock_client(pattern_rows: list | None = None) -> MagicMock:
    client = MagicMock()
    client.query.return_value = pattern_rows or []
    client.execute.return_value = None
    return client


def _mock_v2_output(score: float = 0.3) -> MagicMock:
    """Crea un mock CompositeSignalOutput v2."""
    v2 = MagicMock()
    v2.composite_score = score
    v2.computed_at = datetime.now(UTC)
    v2.recommended_action = "BUY" if score > 0.3 else ("REDUCE" if score < -0.3 else "HOLD")
    v2.confidence = "MEDIUM"
    v2.components_used = ["vix", "macro", "yield_curve", "credit", "claims"]
    v2.vix_component = score * 0.8
    v2.macro_component = score * 0.9
    v2.yield_curve_component = score * 0.7
    v2.credit_component = score * 0.6
    v2.claims_component = score * 0.5
    v2.labour_market_component = score * 0.8
    v2.surprise_component = score * 0.4
    v2.valuation_component = 0.0
    v2.correlation_component = 0.0
    return v2


class TestWeightsV3:
    def test_weights_sum_to_one(self) -> None:
        total = sum(_WEIGHTS_V3.values())
        assert abs(total - 1.0) < 1e-9, f"Pesi V3 non sommano a 1.0: {total}"

    def test_all_weights_positive(self) -> None:
        assert all(w > 0 for w in _WEIGHTS_V3.values())

    def test_expected_components_present(self) -> None:
        expected = {"vix", "macro", "yield_curve", "credit", "claims",
                    "labour_market", "surprise", "valuation", "correlation", "pattern"}
        assert expected == set(_WEIGHTS_V3.keys())


class TestCompositeSignalAggregatorV3:
    def _make_aggregator(self, pattern_rows: list | None = None) -> CompositeSignalAggregatorV3:
        client = _mock_client(pattern_rows=pattern_rows)
        return CompositeSignalAggregatorV3(duckdb=client)

    def test_compute_returns_v3_output(self) -> None:
        agg = self._make_aggregator()
        v2_mock = _mock_v2_output(0.4)
        with patch.object(agg, "_compute_v2_parent", return_value=v2_mock, create=True):
            with patch("engine.analytics.composite_signal_v3."
                       "CompositeSignalAggregator.compute", return_value=v2_mock):
                result = agg.compute()
        assert isinstance(result, CompositeSignalOutputV3)

    def test_compute_score_bounded(self) -> None:
        agg = self._make_aggregator()
        v2_mock = _mock_v2_output(0.5)
        with patch("engine.analytics.composite_signal_v3."
                   "CompositeSignalAggregator.compute", return_value=v2_mock):
            result = agg.compute()
        assert -1.0 <= result.composite_score_v3 <= 1.0

    def test_compute_with_bullish_patterns(self) -> None:
        pattern_rows = [
            ("HS_Inverse", "bullish", 0.80),
            ("Double_Bottom", "bullish", 0.75),
        ]
        agg = self._make_aggregator(pattern_rows=pattern_rows)
        v2_mock = _mock_v2_output(0.1)
        with patch("engine.analytics.composite_signal_v3."
                   "CompositeSignalAggregator.compute", return_value=v2_mock):
            result = agg.compute()
        # Pattern bullish → score dovrebbe salire rispetto a v2
        assert result.pattern_component > 0
        assert result.pattern_count == 2

    def test_compute_with_bearish_patterns(self) -> None:
        pattern_rows = [
            ("Double_Top", "bearish", 0.82),
        ]
        agg = self._make_aggregator(pattern_rows=pattern_rows)
        v2_mock = _mock_v2_output(-0.1)
        with patch("engine.analytics.composite_signal_v3."
                   "CompositeSignalAggregator.compute", return_value=v2_mock):
            result = agg.compute()
        assert result.pattern_component < 0

    def test_compute_no_patterns(self) -> None:
        agg = self._make_aggregator(pattern_rows=[])
        v2_mock = _mock_v2_output(0.3)
        with patch("engine.analytics.composite_signal_v3."
                   "CompositeSignalAggregator.compute", return_value=v2_mock):
            result = agg.compute()
        assert result.pattern_component == 0.0
        assert result.pattern_count == 0

    def test_action_buy_above_threshold(self) -> None:
        agg = self._make_aggregator()
        v2_mock = _mock_v2_output(0.8)
        with patch("engine.analytics.composite_signal_v3."
                   "CompositeSignalAggregator.compute", return_value=v2_mock):
            result = agg.compute()
        assert result.recommended_action_v3 in ("BUY", "HOLD")  # score alto ma meno di 5 componenti

    def test_action_reduce_below_threshold(self) -> None:
        agg = self._make_aggregator()
        v2_mock = _mock_v2_output(-0.8)
        with patch("engine.analytics.composite_signal_v3."
                   "CompositeSignalAggregator.compute", return_value=v2_mock):
            result = agg.compute()
        assert result.recommended_action_v3 in ("REDUCE", "HOLD")

    def test_breakdown_json_valid(self) -> None:
        import json
        agg = self._make_aggregator()
        v2_mock = _mock_v2_output(0.3)
        with patch("engine.analytics.composite_signal_v3."
                   "CompositeSignalAggregator.compute", return_value=v2_mock):
            result = agg.compute()
        breakdown = json.loads(result.breakdown_json_v3)
        assert isinstance(breakdown, dict)

    def test_persist_called(self) -> None:
        client = _mock_client()
        agg = CompositeSignalAggregatorV3(duckdb=client)
        v2_mock = _mock_v2_output(0.2)
        with patch("engine.analytics.composite_signal_v3."
                   "CompositeSignalAggregator.compute", return_value=v2_mock):
            agg.compute()
        assert client.execute.called

    def test_computed_at_propagated(self) -> None:
        agg = self._make_aggregator()
        ts = datetime.now(UTC)
        v2_mock = _mock_v2_output(0.3)
        v2_mock.computed_at = ts
        with patch("engine.analytics.composite_signal_v3."
                   "CompositeSignalAggregator.compute", return_value=v2_mock):
            result = agg.compute()
        assert result.computed_at == ts

    def test_db_error_on_pattern_read_graceful(self) -> None:
        client = _mock_client()
        client.query.side_effect = RuntimeError("DB down")
        agg = CompositeSignalAggregatorV3(duckdb=client)
        v2_mock = _mock_v2_output(0.3)
        with patch("engine.analytics.composite_signal_v3."
                   "CompositeSignalAggregator.compute", return_value=v2_mock):
            result = agg.compute()
        # Deve degradare gracefully: pattern_component = 0.0
        assert result.pattern_component == 0.0


class TestCompositeSignalOutputV3:
    def test_components_used_includes_pattern_when_nonzero(self) -> None:
        v2_mock = _mock_v2_output(0.3)
        v2_mock.components_used = ["vix", "macro"]
        out = CompositeSignalOutputV3(
            v2_output=v2_mock,
            pattern_component=0.5,
            pattern_count=2,
            composite_score_v3=0.4,
            recommended_action_v3="BUY",
            confidence_v3="MEDIUM",
        )
        assert "pattern" in out.components_used

    def test_components_used_excludes_pattern_when_zero(self) -> None:
        v2_mock = _mock_v2_output(0.0)
        v2_mock.components_used = ["vix"]
        out = CompositeSignalOutputV3(
            v2_output=v2_mock,
            pattern_component=0.0,
            pattern_count=0,
            composite_score_v3=0.0,
            recommended_action_v3="HOLD",
            confidence_v3="LOW",
        )
        assert "pattern" not in out.components_used
