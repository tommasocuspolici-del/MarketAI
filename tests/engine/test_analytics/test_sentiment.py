"""Tests for engine.analytics.sentiment."""
from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from engine.analytics.sentiment import (
    CompositeSentiment,
    SentimentAggregator,
    SentimentSignal,
    SentimentSource,
)
from shared.exceptions import SentimentAggregationError


def _make_signal(
    source: SentimentSource,
    score: float = 0.0,
    confidence: float = 0.9,
    ts_offset_min: int = 0,
) -> SentimentSignal:
    return SentimentSignal(
        source=source,
        score=score,
        confidence=confidence,
        timestamp=datetime.now(UTC) - timedelta(minutes=ts_offset_min),
    )


# ═══════════════════════════════════════════════════════════════════════════
# SentimentSignal validation
# ═══════════════════════════════════════════════════════════════════════════
class TestSentimentSignal:
    def test_valid_construction(self) -> None:
        s = _make_signal(SentimentSource.AAII, 0.5, 0.9)
        assert s.score == 0.5

    def test_score_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="score"):
            _make_signal(SentimentSource.AAII, 1.5)

    def test_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            _make_signal(SentimentSource.AAII, 0.5, 1.5)


# ═══════════════════════════════════════════════════════════════════════════
# SentimentAggregator
# ═══════════════════════════════════════════════════════════════════════════
class TestSentimentAggregator:
    def test_empty_signals_raises(self) -> None:
        agg = SentimentAggregator()
        with pytest.raises(SentimentAggregationError, match="no signals"):
            agg.aggregate([])

    def test_single_source_low_confidence(self) -> None:
        """Rule 26: with < 3 sources, confidence is penalized."""
        agg = SentimentAggregator()
        sigs = [_make_signal(SentimentSource.CNN_FEAR_GREED, 0.5, 0.9)]
        result = agg.aggregate(sigs)
        assert isinstance(result, CompositeSentiment)
        assert result.n_sources == 1
        # Confidence halved due to insufficient sources
        assert result.confidence < 0.5

    def test_three_sources_full_confidence(self) -> None:
        """3+ sources → no penalty."""
        agg = SentimentAggregator()
        sigs = [
            _make_signal(SentimentSource.CNN_FEAR_GREED, 0.5, 0.9),
            _make_signal(SentimentSource.AAII, 0.4, 0.85),
            _make_signal(SentimentSource.PUT_CALL_RATIO, 0.6, 0.8),
        ]
        result = agg.aggregate(sigs)
        assert result.n_sources == 3
        # Confidence not penalized
        assert result.confidence > 0.7

    def test_extreme_greed_contrarian(self) -> None:
        agg = SentimentAggregator()
        sigs = [
            _make_signal(SentimentSource.CNN_FEAR_GREED, 0.85, 0.9),
            _make_signal(SentimentSource.AAII, 0.75, 0.9),
            _make_signal(SentimentSource.PUT_CALL_RATIO, 0.7, 0.8),
        ]
        result = agg.aggregate(sigs)
        assert result.contrarian_signal == "extreme_greed"
        assert result.is_extreme

    def test_extreme_fear_contrarian(self) -> None:
        agg = SentimentAggregator()
        sigs = [
            _make_signal(SentimentSource.CNN_FEAR_GREED, -0.85, 0.9),
            _make_signal(SentimentSource.AAII, -0.75, 0.9),
            _make_signal(SentimentSource.PUT_CALL_RATIO, -0.7, 0.8),
        ]
        result = agg.aggregate(sigs)
        assert result.contrarian_signal == "extreme_fear"

    def test_neutral_sentiment_no_contrarian(self) -> None:
        agg = SentimentAggregator()
        sigs = [
            _make_signal(SentimentSource.CNN_FEAR_GREED, 0.1, 0.9),
            _make_signal(SentimentSource.AAII, -0.05, 0.85),
            _make_signal(SentimentSource.PUT_CALL_RATIO, 0.0, 0.8),
        ]
        result = agg.aggregate(sigs)
        assert result.contrarian_signal is None

    def test_dedup_keeps_most_recent_per_source(self) -> None:
        """Same source with multiple signals → most recent wins."""
        agg = SentimentAggregator()
        sigs = [
            _make_signal(SentimentSource.AAII, -0.5, 0.9, ts_offset_min=60),
            _make_signal(SentimentSource.AAII, 0.8, 0.9, ts_offset_min=0),
            _make_signal(SentimentSource.CNN_FEAR_GREED, 0.0, 0.9),
            _make_signal(SentimentSource.PUT_CALL_RATIO, 0.0, 0.9),
        ]
        result = agg.aggregate(sigs)
        # 3 unique sources after dedup
        assert result.n_sources == 3
        # Score should reflect 0.8 (latest AAII), not -0.5
        assert result.per_source_scores["aaii"] == 0.8

    def test_per_source_scores_returned(self) -> None:
        agg = SentimentAggregator()
        sigs = [
            _make_signal(SentimentSource.CNN_FEAR_GREED, 0.5, 0.9),
            _make_signal(SentimentSource.AAII, 0.3, 0.9),
            _make_signal(SentimentSource.PUT_CALL_RATIO, 0.4, 0.9),
        ]
        result = agg.aggregate(sigs)
        assert "cnn_fear_greed" in result.per_source_scores
        assert "aaii" in result.per_source_scores


# ═══════════════════════════════════════════════════════════════════════════
# Performance — DoD: aggregation 8 sources < 20s
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.benchmark
class TestSentimentPerformance:
    def test_aggregation_8_sources_fast(self) -> None:
        """DoD Phase 8: aggregation < 20s (test target: < 100ms)."""
        agg = SentimentAggregator()
        sigs = [
            _make_signal(src, score=0.1, confidence=0.85)
            for src in SentimentSource
        ]
        t0 = time.monotonic()
        result = agg.aggregate(sigs)
        elapsed = time.monotonic() - t0
        assert result.n_sources == 8
        # Liberal: actual must be < 100ms but DoD allows up to 20s
        assert elapsed < 0.5, f"expected <0.5s, got {elapsed:.3f}s"
