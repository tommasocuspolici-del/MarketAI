"""Tests for SourceCredibilityTracker."""
from __future__ import annotations

import pytest

from engine.analytics.sentiment.source_credibility_tracker import SourceCredibilityTracker


class TestDefaultWeights:
    def test_reuters_high_credibility(self) -> None:
        tracker = SourceCredibilityTracker()
        assert tracker.get_weight("reuters") >= 0.85

    def test_twitter_low_credibility(self) -> None:
        tracker = SourceCredibilityTracker()
        assert tracker.get_weight("twitter") <= 0.50

    def test_unknown_source_gets_default(self) -> None:
        tracker = SourceCredibilityTracker()
        w = tracker.get_weight("some_unknown_blog")
        assert 0.0 <= w <= 1.0

    def test_case_insensitive(self) -> None:
        tracker = SourceCredibilityTracker()
        assert tracker.get_weight("Reuters") == tracker.get_weight("reuters")


class TestICUpdate:
    def test_high_ic_increases_weight(self) -> None:
        tracker = SourceCredibilityTracker()
        old = tracker.get_weight("reddit")
        tracker.update_from_ic("reddit", ic_estimate=0.15, sample_size=100)
        new = tracker.get_weight("reddit")
        assert new > old    # IC 0.15 → weight 1.0 → pulls weight up

    def test_low_ic_decreases_weight(self) -> None:
        tracker = SourceCredibilityTracker()
        old = tracker.get_weight("reuters")
        tracker.update_from_ic("reuters", ic_estimate=0.005, sample_size=50)
        new = tracker.get_weight("reuters")
        assert new < old    # IC 0.005 → weight 0.05 → pulls weight down

    def test_weight_stays_bounded(self) -> None:
        tracker = SourceCredibilityTracker()
        tracker.update_from_ic("test_source", ic_estimate=1.0, sample_size=100)
        assert 0.0 <= tracker.get_weight("test_source") <= 1.0

    def test_all_weights_returns_dict(self) -> None:
        tracker = SourceCredibilityTracker()
        weights = tracker.all_weights()
        assert isinstance(weights, dict)
        assert len(weights) > 0


class TestAnnotation:
    def test_annotate_adds_credibility_field(self) -> None:
        tracker = SourceCredibilityTracker()
        articles = [{"title": "News", "source": "reuters"}]
        annotated = tracker.annotate_articles(articles)
        assert "credibility" in annotated[0]

    def test_annotate_returns_same_list(self) -> None:
        tracker = SourceCredibilityTracker()
        articles = [{"title": "A", "source": "reuters"}, {"title": "B", "source": "unknown"}]
        result = tracker.annotate_articles(articles)
        assert len(result) == 2

    def test_missing_source_uses_unknown_weight(self) -> None:
        tracker = SourceCredibilityTracker()
        articles = [{"title": "News"}]   # no 'source' key
        annotated = tracker.annotate_articles(articles)
        assert annotated[0]["credibility"] == tracker.get_weight("unknown")
