"""Tests for SentimentVelocityAnalyzer — DoD: 'reversing' when velocity_1d changes sign."""
from __future__ import annotations

import pytest

from engine.analytics.sentiment.sentiment_velocity import SentimentVelocityAnalyzer


class TestVelocityBasics:
    def test_single_score_insufficient(self) -> None:
        analyzer = SentimentVelocityAnalyzer()
        snap = analyzer.compute([0.5])
        assert snap.velocity_1d is None
        assert snap.regime == "stable"

    def test_two_scores_gives_velocity_1d(self) -> None:
        analyzer = SentimentVelocityAnalyzer()
        snap = analyzer.compute([0.2, 0.5])
        assert snap.velocity_1d == pytest.approx(0.3)

    def test_velocity_5d_requires_6_scores(self) -> None:
        analyzer = SentimentVelocityAnalyzer()
        snap = analyzer.compute([0.1, 0.2, 0.3, 0.4, 0.5])   # only 5
        assert snap.velocity_5d is None

    def test_velocity_5d_computed_with_6_scores(self) -> None:
        analyzer = SentimentVelocityAnalyzer()
        scores = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
        snap = analyzer.compute(scores)
        assert snap.velocity_5d == pytest.approx(0.5 - 0.0)   # last - sixth-from-end

    def test_ticker_propagated(self) -> None:
        analyzer = SentimentVelocityAnalyzer()
        snap = analyzer.compute([0.1, 0.2], ticker="AAPL")
        assert snap.ticker == "AAPL"


class TestRegimeClassification:
    def test_improving_when_velocity_positive(self) -> None:
        analyzer = SentimentVelocityAnalyzer(stable_threshold=0.05)
        scores = [0.1, 0.1, 0.1, 0.1, 0.1, 0.2]   # last rose
        snap = analyzer.compute(scores)
        assert snap.regime == "improving"

    def test_deteriorating_when_velocity_negative(self) -> None:
        analyzer = SentimentVelocityAnalyzer(stable_threshold=0.05)
        scores = [0.5, 0.5, 0.5, 0.5, 0.5, 0.4]   # last fell
        snap = analyzer.compute(scores)
        assert snap.regime == "deteriorating"

    def test_stable_when_small_change(self) -> None:
        analyzer = SentimentVelocityAnalyzer(stable_threshold=0.05)
        scores = [0.5, 0.5, 0.5, 0.5, 0.5, 0.501]   # tiny change
        snap = analyzer.compute(scores)
        assert snap.regime == "stable"

    def test_reversing_when_velocity_1d_changes_sign(self) -> None:
        """DoD: regime = 'reversing' when velocity_1d has opposite sign to velocity_5d."""
        analyzer = SentimentVelocityAnalyzer(stable_threshold=0.05)
        # Trend was improving (5d positive), but last day dropped (1d negative)
        scores = [0.1, 0.2, 0.3, 0.4, 0.5, 0.3]   # was going up, now dropped
        snap = analyzer.compute(scores)
        assert snap.regime == "reversing"   # DoD criterion

    def test_reversing_opposite_case(self) -> None:
        """Regime 'reversing' also when recovery after downtrend."""
        analyzer = SentimentVelocityAnalyzer(stable_threshold=0.05)
        # Was falling (5d negative), but last day rose sharply (1d positive)
        scores = [0.5, 0.4, 0.3, 0.2, 0.1, 0.3]   # was going down, now up
        snap = analyzer.compute(scores)
        assert snap.regime == "reversing"


class TestAcceleration:
    def test_acceleration_requires_3_scores(self) -> None:
        analyzer = SentimentVelocityAnalyzer()
        snap = analyzer.compute([0.1, 0.2])
        assert snap.acceleration is None

    def test_acceleration_computed_with_3_scores(self) -> None:
        analyzer = SentimentVelocityAnalyzer()
        # scores: 0.1, 0.3, 0.6 → v[-1]=0.3, v[-2]=0.2 → accel=0.1
        snap = analyzer.compute([0.1, 0.3, 0.6])
        assert snap.acceleration == pytest.approx(0.1)

    def test_velocity_20d_requires_21_scores(self) -> None:
        analyzer = SentimentVelocityAnalyzer()
        snap = analyzer.compute([0.5] * 20)
        assert snap.velocity_20d is None
        snap2 = analyzer.compute([0.5] * 21)
        assert snap2.velocity_20d is not None
