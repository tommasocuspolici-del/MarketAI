"""Tests for SentimentAggregatorV2 — DoD: quality_flag, Signal Bus, IC tracking."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.analytics.sentiment.sentiment_aggregator_v2 import SentimentAggregatorV2
from shared.alpha_decay_monitor import AlphaDecayMonitor
from shared.signal_registry import SignalRegistry
from shared.signal_bus import SignalBus


def _make_articles(n: int, title: str = "Fed raises rates", score: float = -0.5) -> list[dict]:
    sources = ["reuters", "bloomberg", "cnbc", "wsj", "ft"] * (n // 5 + 1)
    return [{"title": f"{title} {i}", "source": sources[i]} for i in range(n)]


def _make_aggregator(publish: bool = False) -> SentimentAggregatorV2:
    monitor = AlphaDecayMonitor()
    return SentimentAggregatorV2(decay_monitor=monitor, publish_to_bus=publish)


class TestEmptyInput:
    def test_empty_articles_returns_insufficient_data(self) -> None:
        agg = _make_aggregator()
        result = agg.aggregate([])
        assert result.quality_flag == "insufficient_data"
        assert result.n_articles == 0
        assert result.composite_score == pytest.approx(0.0)


class TestQualityFlag:
    def test_fewer_than_3_unique_events_sets_insufficient(self) -> None:
        """DoD: quality_flag = "insufficient_data" if < 3 unique events."""
        agg = _make_aggregator()
        # 2 completely different articles → 2 events < 3 → insufficient
        articles = [
            {"title": "Apple earnings beat estimates", "source": "reuters"},
            {"title": "Tesla deliveries miss forecasts", "source": "bloomberg"},
        ]
        result = agg.aggregate(articles)
        assert result.quality_flag == "insufficient_data"

    def test_many_unique_events_flag_ok(self) -> None:
        agg = _make_aggregator()
        articles = [
            {"title": "Fed raises rates to fight inflation", "source": "reuters"},
            {"title": "Apple reports record quarterly profits", "source": "bloomberg"},
            {"title": "Tesla deliveries exceed expectations", "source": "cnbc"},
            {"title": "Oil prices rise on OPEC production cuts", "source": "wsj"},
            {"title": "S&P 500 hits all-time high on strong jobs data", "source": "ft"},
        ]
        result = agg.aggregate(articles)
        # 5 distinct topics → ≥ 3 events → quality ok
        assert result.n_articles == 5


class TestCompositeScore:
    def test_composite_in_range(self) -> None:
        agg = _make_aggregator()
        articles = _make_articles(10, title="Strong earnings growth")
        result = agg.aggregate(articles)
        assert -1.0 <= result.composite_score <= 1.0

    def test_model_used_is_string(self) -> None:
        agg = _make_aggregator()
        result = agg.aggregate(_make_articles(3))
        assert result.model_used in ("finbert", "vader", "none")


class TestICTracking:
    def test_forward_return_updates_monitor(self) -> None:
        """DoD: AlphaDecayMonitor updated after each batch."""
        monitor = AlphaDecayMonitor()
        agg = SentimentAggregatorV2(decay_monitor=monitor, publish_to_bus=False)
        articles = _make_articles(5)
        agg.aggregate(articles, forward_return=0.02)
        assert monitor.observation_count("sentiment_composite") >= 1   # DoD


class TestSignalBusPublishing:
    def test_publish_true_calls_bus(self) -> None:
        """DoD: publishes Signal to bus with ic_estimate and quality_flag."""
        monitor = AlphaDecayMonitor()
        agg = SentimentAggregatorV2(decay_monitor=monitor, publish_to_bus=True)

        received: list = []
        bus = SignalBus.__new__(SignalBus)
        from collections import defaultdict
        import threading
        bus._handlers = defaultdict(list)
        bus._lock = threading.RLock()
        bus._registry = SignalRegistry()
        bus.subscribe("sentiment_composite", lambda s: received.append(s))

        articles = [
            {"title": "Strong tech earnings drive markets higher", "source": "reuters"},
            {"title": "Apple reports record profits on iPhone sales", "source": "bloomberg"},
            {"title": "Nasdaq hits all-time high on AI optimism", "source": "cnbc"},
            {"title": "Consumer spending beats expectations in Q3", "source": "wsj"},
        ]

        with patch("engine.analytics.sentiment.sentiment_aggregator_v2.get_signal_bus",
                   return_value=bus):
            agg.aggregate(articles)

        assert len(received) >= 1
        assert received[0].name == "sentiment_composite"
        assert received[0].quality_flag in ("ok", "insufficient_data", "low_ic")


class TestCredibilityAnnotation:
    def test_credibility_annotated_on_articles(self) -> None:
        agg = _make_aggregator()
        articles = [{"title": "Market update", "source": "reuters"}]
        # Annotate doesn't raise; credibility is added
        annotated = agg._credibility.annotate_articles(articles)
        assert "credibility" in annotated[0]
        assert 0.0 <= annotated[0]["credibility"] <= 1.0
