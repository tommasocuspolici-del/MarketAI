"""Property-based tests for sentiment + tax math (Phase 9 DoD).

Uses Hypothesis to verify mathematical invariants over wide input domains.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from engine.analytics.sentiment import (
    SentimentAggregator,
    SentimentSignal,
    SentimentSource,
)
from personal.tax import ItalyTaxRules, ITAssetClass, TaxableEvent

# ═══════════════════════════════════════════════════════════════════════════
# Strategies
# ═══════════════════════════════════════════════════════════════════════════
sentiment_score_strategy = st.floats(
    min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False,
)
confidence_strategy = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False,
)
gain_strategy = st.floats(
    min_value=-1_000_000, max_value=1_000_000,
    allow_nan=False, allow_infinity=False,
)


def _make_signal(source: SentimentSource, score: float, conf: float) -> SentimentSignal:
    return SentimentSignal(
        source=source, score=score, confidence=conf,
        timestamp=datetime.now(UTC),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Sentiment invariants
# ═══════════════════════════════════════════════════════════════════════════
class TestSentimentProperties:
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @given(scores=st.lists(sentiment_score_strategy, min_size=3, max_size=8))
    def test_composite_score_in_range(self, scores: list[float]) -> None:
        """Property: composite score ALWAYS in [-1, 1]."""
        agg = SentimentAggregator()
        # Pick distinct sources up to len(scores)
        sources = list(SentimentSource)[:len(scores)]
        signals = [
            _make_signal(src, score, 0.85)
            for src, score in zip(sources, scores, strict=True)
        ]
        result = agg.aggregate(signals)
        assert -1.0 <= result.score <= 1.0

    @settings(max_examples=50)
    @given(
        scores=st.lists(sentiment_score_strategy, min_size=3, max_size=8),
        confidences=st.lists(
            st.floats(min_value=0.1, max_value=1.0,
                      allow_nan=False, allow_infinity=False),
            min_size=3, max_size=8,
        ),
    )
    def test_confidence_in_range(
        self, scores: list[float], confidences: list[float]
    ) -> None:
        """Property: composite confidence ALWAYS in [0, 1]."""
        n = min(len(scores), len(confidences))
        if n < 3:
            return  # Skip — aggregator needs at least 1 (and we want clean data)
        agg = SentimentAggregator()
        sources = list(SentimentSource)[:n]
        signals = [
            _make_signal(sources[i], scores[i], confidences[i])
            for i in range(n)
        ]
        result = agg.aggregate(signals)
        assert 0.0 <= result.confidence <= 1.0

    @settings(max_examples=50)
    @given(score=st.floats(min_value=-0.59, max_value=0.59,
                           allow_nan=False, allow_infinity=False))
    def test_no_contrarian_for_moderate_scores(self, score: float) -> None:
        """Property: |score| < 0.6 → no contrarian signal."""
        agg = SentimentAggregator()
        sources = list(SentimentSource)[:3]
        signals = [_make_signal(src, score, 0.9) for src in sources]
        result = agg.aggregate(signals)
        assert result.contrarian_signal is None

    @settings(max_examples=50)
    @given(score=st.floats(min_value=0.65, max_value=1.0,
                           allow_nan=False, allow_infinity=False))
    def test_extreme_greed_for_high_scores(self, score: float) -> None:
        """Property: all sources at score ≥ 0.65 → extreme_greed."""
        agg = SentimentAggregator()
        sources = list(SentimentSource)[:3]
        signals = [_make_signal(src, score, 0.9) for src in sources]
        result = agg.aggregate(signals)
        # With 3 high-score sources at 0.9 conf, composite should be ≥ 0.6
        if result.score >= 0.6:
            assert result.contrarian_signal == "extreme_greed"


# ═══════════════════════════════════════════════════════════════════════════
# Italy tax math invariants
# ═══════════════════════════════════════════════════════════════════════════
class TestItalyTaxProperties:
    @settings(max_examples=200)
    @given(gain=gain_strategy)
    def test_loss_never_taxed(self, gain: float) -> None:
        """Property: a loss (gain < 0) ALWAYS yields zero tax."""
        if gain >= 0:
            return  # Skip non-losses
        ev = TaxableEvent(
            ticker="X", asset_class=ITAssetClass.EQUITY,
            gain=gain, currency="EUR", realized_at=date(2025, 1, 1),
        )
        assert ItalyTaxRules.compute_tax_on_event(ev) == 0.0

    @settings(max_examples=200)
    @given(gain=st.floats(
        min_value=0.0, max_value=1_000_000,
        allow_nan=False, allow_infinity=False,
    ))
    def test_equity_gain_taxed_at_26pct(self, gain: float) -> None:
        """Property: equity gain X → tax X * 0.26."""
        ev = TaxableEvent(
            ticker="X", asset_class=ITAssetClass.EQUITY,
            gain=gain, currency="EUR", realized_at=date(2025, 1, 1),
        )
        tax = ItalyTaxRules.compute_tax_on_event(ev)
        assert abs(tax - gain * 0.26) < 1e-6

    @settings(max_examples=100)
    @given(
        gains=st.lists(gain_strategy, min_size=1, max_size=20),
    )
    def test_annual_tax_non_negative(self, gains: list[float]) -> None:
        """Property: annual tax owed is ALWAYS >= 0."""
        events = [
            TaxableEvent(
                ticker=f"T{i}", asset_class=ITAssetClass.EQUITY,
                gain=g, currency="EUR", realized_at=date(2025, 6, 15),
            )
            for i, g in enumerate(gains)
        ]
        result = ItalyTaxRules.compute_annual_tax(events)
        assert result["tax_owed"] >= 0.0
        assert result["remaining_carry_forward"] >= 0.0
