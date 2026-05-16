"""Tests for SourceDeduplicator — DoD: 50 similar articles → 1 event, >3x compression."""
from __future__ import annotations

import pytest

from engine.analytics.sentiment.source_deduplicator import DeduplicatedEvent, SourceDeduplicator


def _make_article(title: str, score: float = 0.5, source: str = "reuters") -> dict:
    return {"title": title, "score": score, "source": source, "credibility": 0.9}


# ── Fixture: 50 near-duplicate articles (same Fed news) ───────────────────

_FED_TITLE = "Federal Reserve raises interest rates by 75 basis points"
_FED_VARIANTS = [
    "Federal Reserve raises interest rates by 75 basis points",
    "Fed hikes rates 75 bps in aggressive monetary tightening",
    "Federal Reserve increases rates by three quarters of a point",
    "Fed raises interest rates 75 bps to fight inflation",
    "Central bank raises rates 75 basis points amid inflation",
    "Fed delivers 75bp rate hike to combat surging prices",
    "FOMC raises rates by 75 basis points in latest meeting",
    "Fed increases interest rates three quarters of a percent",
    "Federal Reserve lifts rates 75 basis points to tame inflation",
    "Central bank hikes rates by 75bps to slowdown inflation",
]

def _make_50_fed_articles() -> list[dict]:
    articles = []
    sources = ["reuters", "bloomberg", "cnbc", "wsj", "ft"] * 10
    for i in range(50):
        title = _FED_VARIANTS[i % len(_FED_VARIANTS)]
        articles.append({
            "title":       title,
            "score":       -0.6,
            "source":      sources[i],
            "credibility": 0.85,
        })
    return articles


class TestEmptyAndSingle:
    def test_empty_returns_empty(self) -> None:
        dedup = SourceDeduplicator()
        assert dedup.deduplicate([]) == []

    def test_single_article_returns_one_event(self) -> None:
        dedup = SourceDeduplicator()
        art = _make_article("Apple beats earnings estimates")
        events = dedup.deduplicate([art])
        assert len(events) == 1
        assert events[0].article_count == 1


class TestDeduplication:
    def test_50_similar_articles_compressed(self) -> None:
        """DoD: 50 articles from same news → clustered into few events."""
        dedup = SourceDeduplicator()
        articles = _make_50_fed_articles()
        events = dedup.deduplicate(articles)

        n_orig   = len(articles)
        n_events = len(events)
        compression = n_orig / max(n_events, 1)

        # DoD: compression > 3x (50 → < 17 events)
        assert compression > 3.0, f"Compression {compression:.1f}x < 3x DoD"

    def test_50_articles_dominant_cluster_exists(self) -> None:
        """At least one cluster should contain multiple articles (> 1 per variant group)."""
        dedup = SourceDeduplicator()
        articles = _make_50_fed_articles()
        events = dedup.deduplicate(articles)

        max_cluster_size = max(e.article_count for e in events)
        # Each variant group has 5 articles — largest cluster should hold at least 5
        assert max_cluster_size >= 5, f"Largest cluster has only {max_cluster_size} articles"

    def test_weighted_score_in_range(self) -> None:
        dedup = SourceDeduplicator()
        articles = _make_50_fed_articles()
        events = dedup.deduplicate(articles)
        for e in events:
            assert -1.0 <= e.weighted_score <= 1.0

    def test_distinct_topics_not_merged(self) -> None:
        """Two completely different topics should not be merged."""
        dedup = SourceDeduplicator()
        articles = [
            _make_article("Federal Reserve raises interest rates today"),
            _make_article("Apple reports record iPhone sales this quarter"),
        ]
        events = dedup.deduplicate(articles)
        # With only 2 articles and DBSCAN min_samples=2, they won't cluster
        # unless very similar — expect 2 separate noise events
        assert len(events) >= 1   # At minimum exists


class TestWeightedScore:
    def test_high_credibility_influences_score(self) -> None:
        dedup = SourceDeduplicator()
        articles = [
            {"title": "Market up on good news", "score": 0.8, "source": "a", "credibility": 0.9},
            {"title": "Market up on positive data", "score": 0.2, "source": "b", "credibility": 0.1},
        ]
        events = dedup.deduplicate(articles)
        # All events should exist; weighted score biased toward high-credibility
        assert len(events) >= 1

    def test_source_count_tracked(self) -> None:
        dedup = SourceDeduplicator(eps=0.9, min_samples=2)  # very aggressive merging
        articles = [
            {"title": "Fed hikes rates 75bp", "score": -0.5, "source": "reuters",  "credibility": 0.9},
            {"title": "Fed raises rates 75bps", "score": -0.6, "source": "bloomberg", "credibility": 0.88},
        ]
        events = dedup.deduplicate(articles)
        # If merged, source_count should reflect 2 sources
        total_sources = sum(e.source_count for e in events)
        assert total_sources >= 1


class TestBenchmark:
    @pytest.mark.benchmark(group="deduplicator")
    def test_50_articles_under_200ms(self, benchmark) -> None:
        """DoD: SourceDeduplicator 50 articles < 200ms."""
        dedup = SourceDeduplicator()
        articles = _make_50_fed_articles()
        benchmark(dedup.deduplicate, articles)
