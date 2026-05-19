"""Tests — ArticleCleaner (Fase 7)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from engine.news.article_cleaner import ArticleCleaner, _normalize_text, _truncate
from engine.news.schemas import NewsArticle, NewsCategory


def _make_article(
    url: str = "https://example.com/news/1",
    title: str = "Test article title",
    source: str = "TestSource",
) -> NewsArticle:
    return NewsArticle(
        article_id="test-1",
        url=url,
        title=title,
        source=source,
        published_at=datetime.now(UTC),
    )


class TestArticleCleaner:
    def test_clean_sets_content_hash(self) -> None:
        cleaner = ArticleCleaner()
        article = _make_article()
        cleaned = cleaner.clean(article)
        assert cleaned.content_hash is not None
        assert len(cleaned.content_hash) == 32

    def test_clean_not_duplicate_first_time(self) -> None:
        cleaner = ArticleCleaner()
        article = _make_article()
        cleaned = cleaner.clean(article)
        assert cleaned.is_duplicate is False
        assert cleaned.data_quality != "duplicate"

    def test_clean_marks_duplicate(self) -> None:
        cleaner = ArticleCleaner()
        a1 = _make_article(url="https://x.com/1", title="Same title")
        a2 = _make_article(url="https://x.com/1", title="Same title")
        cleaner.clean(a1)
        cleaner.clean(a2)
        assert a1.is_duplicate is False
        assert a2.is_duplicate is True
        assert a2.data_quality == "duplicate"

    def test_clean_different_urls_not_duplicate(self) -> None:
        cleaner = ArticleCleaner()
        a1 = _make_article(url="https://x.com/1", title="Title A")
        a2 = _make_article(url="https://x.com/2", title="Title B")
        cleaner.clean(a1)
        cleaner.clean(a2)
        assert a1.is_duplicate is False
        assert a2.is_duplicate is False

    def test_clean_sets_fetched_at(self) -> None:
        cleaner = ArticleCleaner()
        article = _make_article()
        article.fetched_at = None
        cleaned = cleaner.clean(article)
        assert cleaned.fetched_at is not None

    def test_clean_batch_unique(self) -> None:
        cleaner = ArticleCleaner()
        articles = [
            _make_article(url=f"https://x.com/{i}", title=f"Title {i}")
            for i in range(5)
        ]
        cleaned = cleaner.clean_batch(articles)
        assert all(not a.is_duplicate for a in cleaned)

    def test_clean_batch_with_duplicates(self) -> None:
        cleaner = ArticleCleaner()
        articles = [
            _make_article(url="https://x.com/same", title="Same"),
            _make_article(url="https://x.com/same", title="Same"),
            _make_article(url="https://x.com/unique", title="Unique"),
        ]
        cleaned = cleaner.clean_batch(articles)
        duplicates = [a for a in cleaned if a.is_duplicate]
        assert len(duplicates) == 1

    def test_filter_unique(self) -> None:
        cleaner = ArticleCleaner()
        articles = [
            _make_article(url="https://x.com/1", title="A"),
            _make_article(url="https://x.com/1", title="A"),
        ]
        cleaned = cleaner.clean_batch(articles)
        unique = cleaner.filter_unique(cleaned)
        assert len(unique) == 1

    def test_existing_hashes_treated_as_duplicates(self) -> None:
        cleaner = ArticleCleaner()
        article = _make_article(url="https://x.com/1", title="Title")
        existing_hash = cleaner.compute_hash("https://x.com/1", "Title")
        cleaned = cleaner.clean_batch([article], existing_hashes={existing_hash})
        assert cleaned[0].is_duplicate is True

    def test_reset_clears_seen_hashes(self) -> None:
        cleaner = ArticleCleaner()
        a1 = _make_article(url="https://x.com/1", title="T")
        cleaner.clean(a1)
        cleaner.reset()
        a2 = _make_article(url="https://x.com/1", title="T")
        cleaner.clean(a2)
        assert a2.is_duplicate is False

    def test_title_normalized(self) -> None:
        cleaner = ArticleCleaner()
        article = _make_article(title="  Multiple   spaces  here  ")
        cleaned = cleaner.clean(article)
        assert "  " not in cleaned.title
        assert cleaned.title == "Multiple spaces here"


class TestNormalizeText:
    def test_strips_whitespace(self) -> None:
        assert _normalize_text("  hello  ") == "hello"

    def test_collapses_spaces(self) -> None:
        assert _normalize_text("a  b   c") == "a b c"

    def test_empty_string(self) -> None:
        assert _normalize_text("") == ""

    def test_removes_control_chars(self) -> None:
        assert "\x00" not in _normalize_text("hello\x00world")


class TestTruncate:
    def test_short_string_unchanged(self) -> None:
        assert _truncate("hello", 100) == "hello"

    def test_long_string_truncated(self) -> None:
        result = _truncate("a" * 200, 50)
        assert len(result) == 50
        assert result.endswith("...")

    def test_exact_length_unchanged(self) -> None:
        s = "a" * 50
        assert _truncate(s, 50) == s
