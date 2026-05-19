"""Tests — RelevanceScorer (Fase 7)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from engine.news.relevance_scorer import RelevanceScorer, _is_high_credibility
from engine.news.schemas import NewsArticle, NewsCategory


def _make_article(
    tickers: list[str] | None = None,
    source: str = "Generic News",
    category: NewsCategory = NewsCategory.UNKNOWN,
) -> NewsArticle:
    return NewsArticle(
        article_id="test-1",
        url="https://example.com/news/1",
        title="Market news",
        source=source,
        published_at=datetime.now(UTC),
        category=category,
        tickers=tickers or [],
    )


class TestRelevanceScorer:
    def test_base_score_always_present(self) -> None:
        scorer = RelevanceScorer(watched_tickers=["SPY"])
        article = _make_article(tickers=[], source="Unknown", category=NewsCategory.UNKNOWN)
        score = scorer.score(article)
        assert score >= 0.3

    def test_ticker_match_increases_score(self) -> None:
        scorer = RelevanceScorer(watched_tickers=["SPY", "AAPL"])
        no_match = _make_article(tickers=["XYZ"])
        with_match = _make_article(tickers=["SPY"])
        assert scorer.score(with_match) > scorer.score(no_match)

    def test_macro_category_bonus(self) -> None:
        scorer = RelevanceScorer(watched_tickers=[])
        macro = _make_article(category=NewsCategory.MACRO)
        unknown = _make_article(category=NewsCategory.UNKNOWN)
        assert scorer.score(macro) > scorer.score(unknown)

    def test_central_bank_category_bonus(self) -> None:
        scorer = RelevanceScorer(watched_tickers=[])
        cb = _make_article(category=NewsCategory.CENTRAL_BANK)
        score = scorer.score(cb)
        assert score > 0.3

    def test_high_credibility_source_bonus(self) -> None:
        scorer = RelevanceScorer(watched_tickers=[])
        reuters = _make_article(source="Reuters")
        generic = _make_article(source="Some Blog")
        assert scorer.score(reuters) > scorer.score(generic)

    def test_score_capped_at_1(self) -> None:
        scorer = RelevanceScorer(watched_tickers=["SPY"])
        article = _make_article(
            tickers=["SPY"], source="Reuters", category=NewsCategory.MACRO
        )
        score = scorer.score(article)
        assert score <= 1.0

    def test_score_updates_impact_score(self) -> None:
        scorer = RelevanceScorer(watched_tickers=["AAPL"])
        article = _make_article(tickers=["AAPL"])
        scorer.score(article)
        assert article.impact_score > 0.3

    def test_score_batch_updates_all(self) -> None:
        scorer = RelevanceScorer(watched_tickers=["SPY"])
        articles = [_make_article(tickers=[]) for _ in range(5)]
        scored = scorer.score_batch(articles)
        assert all(a.impact_score >= 0.3 for a in scored)

    def test_filter_relevant(self) -> None:
        scorer = RelevanceScorer(watched_tickers=["SPY"])
        articles = [
            _make_article(tickers=["SPY"]),   # high score
            _make_article(tickers=[]),          # low score
        ]
        scorer.score_batch(articles)
        relevant = scorer.filter_relevant(articles, min_score=0.5)
        assert len(relevant) == 1

    def test_add_ticker_runtime(self) -> None:
        scorer = RelevanceScorer(watched_tickers=[])
        assert scorer.watched_count == 0
        scorer.add_ticker("NVDA")
        assert scorer.watched_count == 1
        article = _make_article(tickers=["NVDA"])
        score = scorer.score(article)
        assert score >= 0.7

    def test_ticker_case_insensitive(self) -> None:
        scorer = RelevanceScorer(watched_tickers=["spy"])
        article = _make_article(tickers=["SPY"])
        score = scorer.score(article)
        assert score >= 0.7


class TestHighCredibility:
    def test_reuters_high(self) -> None:
        assert _is_high_credibility("reuters") is True

    def test_cnbc_high(self) -> None:
        assert _is_high_credibility("CNBC") is True

    def test_ft_high(self) -> None:
        assert _is_high_credibility("Financial Times") is True

    def test_unknown_not_high(self) -> None:
        assert _is_high_credibility("My Blog") is False
