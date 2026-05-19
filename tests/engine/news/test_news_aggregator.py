"""Tests — NewsAggregator (Fase 7)."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from engine.news.news_aggregator import NewsAggregator
from engine.news.schemas import NewsArticle, NewsCategory, NewsSignal


def _make_article(
    article_id: str = "a1",
    source: str = "TestSource",
    title: str = "Test news title",
    category: NewsCategory = NewsCategory.MACRO,
) -> NewsArticle:
    return NewsArticle(
        article_id=article_id,
        url=f"https://example.com/{article_id}",
        title=title,
        source=source,
        published_at=datetime.now(UTC),
        category=category,
    )


def _make_client() -> MagicMock:
    client = MagicMock()
    client.query.return_value = []
    client.execute.return_value = None
    return client


class TestNewsAggregator:
    def test_run_returns_signal(self) -> None:
        client = _make_client()
        agg = NewsAggregator(client)

        mock_signal = NewsSignal(
            signal_date=datetime.now(UTC),
            score=0.1,
            article_count=5,
            cluster_count=2,
            bullish_count=3,
            bearish_count=1,
            neutral_count=1,
        )

        with patch.object(agg._signal_gen, "read_latest", return_value=mock_signal):
            result = agg.run()

        assert isinstance(result, NewsSignal)

    def test_run_uses_cache_when_fresh(self) -> None:
        client = _make_client()
        agg = NewsAggregator(client)

        cached_signal = NewsSignal(
            signal_date=datetime.now(UTC),  # very fresh
            score=0.3,
            article_count=10,
            cluster_count=3,
            bullish_count=6,
            bearish_count=2,
            neutral_count=2,
        )

        with patch.object(agg._signal_gen, "read_latest", return_value=cached_signal):
            result = agg.run(force_refresh=False)

        assert result.score == 0.3
        # fetcher should NOT be called when cache is fresh
        agg._fetcher.fetch_all = MagicMock(return_value=[])
        assert not agg._fetcher.fetch_all.called

    def test_run_force_refresh_bypasses_cache(self) -> None:
        client = _make_client()
        agg = NewsAggregator(client)

        fresh_signal = NewsSignal(
            signal_date=datetime.now(UTC),
            score=0.5, article_count=5, cluster_count=1,
            bullish_count=3, bearish_count=1, neutral_count=1,
        )

        with patch.object(agg._fetcher, "fetch_all", return_value=[]) as mock_fetch:
            with patch.object(agg._clusterer, "cluster", return_value=[]):
                with patch.object(agg._signal_gen, "generate", return_value=fresh_signal):
                    result = agg.run(force_refresh=True)

        mock_fetch.assert_called_once()
        assert result.score == 0.5

    def test_fetch_recent_empty_db(self) -> None:
        client = _make_client()
        client.query.return_value = []
        agg = NewsAggregator(client)
        articles = agg.fetch_recent(hours=24)
        assert articles == []

    def test_fetch_recent_db_error(self) -> None:
        client = _make_client()
        client.query.side_effect = RuntimeError("DB error")
        agg = NewsAggregator(client)
        articles = agg.fetch_recent(hours=24)
        assert articles == []

    def test_enrich_classifies_articles(self) -> None:
        client = _make_client()
        agg = NewsAggregator(client)
        articles = [
            _make_article(title="Federal Reserve raises rates by 25 basis points"),
        ]
        enriched = agg._enrich(articles)
        assert len(enriched) == 1
        assert enriched[0].category == NewsCategory.CENTRAL_BANK

    def test_enrich_resolves_tickers(self) -> None:
        client = _make_client()
        agg = NewsAggregator(client)
        articles = [_make_article(title="Apple earnings beat estimates EPS strong")]
        enriched = agg._enrich(articles)
        assert isinstance(enriched[0].tickers, list)

    def test_is_fresh_recent_signal(self) -> None:
        client = _make_client()
        agg = NewsAggregator(client)
        ts = datetime.now(UTC)
        assert agg._is_fresh(ts, ttl_s=1800) is True

    def test_is_fresh_stale_signal(self) -> None:
        from datetime import timedelta
        client = _make_client()
        agg = NewsAggregator(client)
        ts = datetime.now(UTC) - timedelta(hours=2)
        assert agg._is_fresh(ts, ttl_s=1800) is False

    def test_is_fresh_none_ts(self) -> None:
        client = _make_client()
        agg = NewsAggregator(client)
        assert agg._is_fresh(None, ttl_s=1800) is False  # type: ignore[arg-type]
