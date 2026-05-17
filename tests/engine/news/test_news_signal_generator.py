"""Tests — NewsSignalGenerator (Fase 7 — ★ CP-01)."""
from datetime import UTC, datetime

import pytest

from engine.news.schemas import NewsArticle, NewsCategory
from engine.news.news_signal_generator import NewsSignalGenerator


def _make_article(
    title: str,
    source: str = "reuters",
    sentiment: float | None = None,
    category: NewsCategory = NewsCategory.MACRO,
    hours_ago: int = 1,
) -> NewsArticle:
    from datetime import timedelta
    return NewsArticle(
        article_id=f"test_{hash(title)}",
        url=f"https://example.com/{hash(title)}",
        title=title,
        source=source,
        published_at=datetime.now(UTC) - timedelta(hours=hours_ago),
        category=category,
        sentiment_score=sentiment,
    )


@pytest.fixture
def gen() -> NewsSignalGenerator:
    return NewsSignalGenerator(client=None)


def test_empty_articles_returns_zero(gen: NewsSignalGenerator) -> None:
    signal = gen.generate([])
    assert signal.score == 0.0
    assert signal.article_count == 0
    assert signal.data_quality == "no_data"


def test_bullish_title_positive_score(gen: NewsSignalGenerator) -> None:
    articles = [
        _make_article("Markets surge on strong GDP growth report"),
        _make_article("Stocks rally to record high on positive data"),
    ]
    signal = gen.generate(articles)
    assert signal.score > 0.0
    assert signal.bullish_count >= 1


def test_bearish_title_negative_score(gen: NewsSignalGenerator) -> None:
    articles = [
        _make_article("Market crash fears as recession risk rises"),
        _make_article("Stocks plunge on inflation concerns"),
    ]
    signal = gen.generate(articles)
    assert signal.score < 0.0


def test_score_in_valid_range(gen: NewsSignalGenerator) -> None:
    articles = [_make_article(f"News {i}", sentiment=(-1)**i * 0.5) for i in range(20)]
    signal = gen.generate(articles)
    assert -1.0 <= signal.score <= 1.0


def test_explicit_sentiment_used(gen: NewsSignalGenerator) -> None:
    articles = [
        _make_article("Article 1", sentiment=0.9),
        _make_article("Article 2", sentiment=0.8),
    ]
    signal = gen.generate(articles)
    assert signal.score > 0.5


def test_old_articles_excluded(gen: NewsSignalGenerator) -> None:
    articles = [_make_article("Very old news", hours_ago=48)]
    signal = gen.generate(articles, lookback_hours=24)
    assert signal.article_count == 0


def test_signal_has_required_fields(gen: NewsSignalGenerator) -> None:
    articles = [_make_article("Test article")]
    signal = gen.generate(articles)
    assert signal.signal_date is not None
    assert isinstance(signal.bullish_count, int)
    assert isinstance(signal.bearish_count, int)
    assert isinstance(signal.neutral_count, int)
