"""Tests for engine.news.rss_fetcher."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import httpx
import pytest

from engine.news.rss_fetcher import RSSFetcher, _sha256
from engine.news.schemas import NewsArticle


_RSS_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Article One</title>
    <link>http://example.com/1</link>
    <pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate>
    <description>Summary one</description>
  </item>
  <item>
    <title>Article Two</title>
    <link>http://example.com/2</link>
    <pubDate>Tue, 02 Jan 2024 00:00:00 +0000</pubDate>
    <description>Summary two</description>
  </item>
</channel></rss>"""

_ATOM_XML = """<?xml version="1.0"?>
<feed>
  <entry>
    <title>Atom Entry</title>
    <link>http://example.com/atom1</link>
    <updated>2024-01-01T00:00:00Z</updated>
    <summary>Atom summary</summary>
  </entry>
</feed>"""

_EMPTY_RSS = """<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>"""


def _make_fetcher() -> RSSFetcher:
    with patch("httpx.Client"), \
         patch("engine.news.rss_fetcher._CONFIG_PATH") as mock_path:
        mock_path.exists.return_value = False
        fetcher = RSSFetcher(client=MagicMock())
    return fetcher


def _make_article(url: str = "http://a.com/1", title: str = "T1") -> NewsArticle:
    ch = _sha256(url + title)
    return NewsArticle(
        article_id=f"src_{ch}",
        url=url,
        title=title,
        source="reuters",
        published_at=datetime.now(UTC),
        content_hash=ch,
        fetched_at=datetime.now(UTC),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

class TestHelpers:
    def test_sha256_returns_32_chars(self) -> None:
        result = _sha256("hello world")
        assert len(result) == 32
        assert isinstance(result, str)

    def test_sha256_deterministic(self) -> None:
        assert _sha256("abc") == _sha256("abc")

    def test_sha256_different_inputs(self) -> None:
        assert _sha256("abc") != _sha256("xyz")


# ── Init / _load_sources ──────────────────────────────────────────────────────

class TestInit:
    def test_default_sources_loaded_when_no_yaml(self) -> None:
        fetcher = _make_fetcher()
        assert len(fetcher._sources) > 0
        assert all("rss_url" in s for s in fetcher._sources)

    def test_yaml_sources_loaded(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        yaml_file = tmp_path / "news_sources.yaml"
        yaml_file.write_text(
            "news_sources:\n"
            "  - id: my_source\n"
            "    rss_url: http://test.com/rss\n"
            "    fetch_interval_seconds: 900\n"
        )
        with patch("httpx.Client"), \
             patch("engine.news.rss_fetcher._CONFIG_PATH", yaml_file):
            fetcher = RSSFetcher(client=MagicMock())
        assert len(fetcher._sources) == 1
        assert fetcher._sources[0]["id"] == "my_source"


# ── _has_fresh_cache() ────────────────────────────────────────────────────────

class TestHasFreshCache:
    def test_fresh_timestamp_returns_true(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.query.return_value = [(datetime.now(UTC),)]
        assert fetcher._has_fresh_cache("reuters", 1800) is True

    def test_stale_timestamp_returns_false(self) -> None:
        fetcher = _make_fetcher()
        old = datetime.now(UTC) - timedelta(seconds=3600)
        fetcher._client.query.return_value = [(old,)]
        assert fetcher._has_fresh_cache("reuters", 1800) is False

    def test_empty_result_returns_false(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.query.return_value = []
        assert fetcher._has_fresh_cache("reuters", 1800) is False

    def test_none_fetched_at_returns_false(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.query.return_value = [(None,)]
        assert fetcher._has_fresh_cache("reuters", 1800) is False

    def test_db_exception_returns_false(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.query.side_effect = Exception("DB error")
        assert fetcher._has_fresh_cache("reuters", 1800) is False

    def test_naive_datetime_handled(self) -> None:
        fetcher = _make_fetcher()
        naive = datetime.utcnow()  # noqa: DTZ003
        fetcher._client.query.return_value = [(naive,)]
        result = fetcher._has_fresh_cache("reuters", 1800)
        assert isinstance(result, bool)


# ── _parse_feed() ─────────────────────────────────────────────────────────────

class TestParseFeed:
    def test_rss_feed_parsed(self) -> None:
        fetcher = _make_fetcher()
        articles = fetcher._parse_feed(_RSS_XML, "reuters", {"id": "reuters"})
        assert len(articles) == 2
        assert articles[0].title == "Article One"
        assert articles[1].title == "Article Two"

    def test_atom_feed_parsed(self) -> None:
        fetcher = _make_fetcher()
        articles = fetcher._parse_feed(_ATOM_XML, "test", {"id": "test"})
        assert len(articles) == 1
        assert articles[0].title == "Atom Entry"

    def test_empty_channel_returns_empty(self) -> None:
        fetcher = _make_fetcher()
        articles = fetcher._parse_feed(_EMPTY_RSS, "reuters", {"id": "reuters"})
        assert articles == []

    def test_missing_pub_date_defaults_utc(self) -> None:
        xml = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>No Date</title>
    <link>http://example.com/nodate</link>
  </item>
</channel></rss>"""
        fetcher = _make_fetcher()
        articles = fetcher._parse_feed(xml, "reuters", {"id": "reuters"})
        assert len(articles) == 1
        assert articles[0].published_at.tzinfo is not None

    def test_malformed_date_handled(self) -> None:
        xml = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Bad Date</title>
    <link>http://example.com/baddate</link>
    <pubDate>not-a-valid-date</pubDate>
  </item>
</channel></rss>"""
        fetcher = _make_fetcher()
        articles = fetcher._parse_feed(xml, "reuters", {"id": "reuters"})
        assert len(articles) == 1
        assert articles[0].published_at.tzinfo is not None

    def test_max_50_items_truncated(self) -> None:
        items = "".join(
            f"<item><title>T{i}</title><link>http://a.com/{i}</link>"
            f"<pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate></item>"
            for i in range(60)
        )
        xml = f"<?xml version='1.0'?><rss version='2.0'><channel>{items}</channel></rss>"
        fetcher = _make_fetcher()
        articles = fetcher._parse_feed(xml, "reuters", {"id": "reuters"})
        assert len(articles) == 50

    def test_item_without_link_skipped(self) -> None:
        xml = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>Title Only</title></item>
  <item><title>Both</title><link>http://a.com/2</link></item>
</channel></rss>"""
        fetcher = _make_fetcher()
        articles = fetcher._parse_feed(xml, "reuters", {"id": "reuters"})
        assert len(articles) == 1
        assert articles[0].title == "Both"

    def test_invalid_xml_returns_empty(self) -> None:
        fetcher = _make_fetcher()
        articles = fetcher._parse_feed("this is not xml!!!", "reuters", {"id": "reuters"})
        assert articles == []

    def test_article_has_content_hash(self) -> None:
        fetcher = _make_fetcher()
        articles = fetcher._parse_feed(_RSS_XML, "reuters", {"id": "reuters"})
        assert all(a.content_hash is not None for a in articles)
        assert all(len(a.content_hash) == 32 for a in articles)  # type: ignore[arg-type]


# ── fetch_source() ────────────────────────────────────────────────────────────

class TestFetchSource:
    def _source(self) -> dict:
        return {"id": "reuters", "rss_url": "http://rss.test/feed", "fetch_interval_seconds": 1800}

    def test_success_returns_articles(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.query.return_value = []  # no cache, no dedup
        mock_resp = MagicMock()
        mock_resp.text = _RSS_XML
        mock_resp.raise_for_status.return_value = None
        fetcher._http.get.return_value = mock_resp

        articles = fetcher.fetch_source(self._source())
        assert len(articles) == 2

    def test_cache_hit_skips_http(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.query.return_value = [(datetime.now(UTC),)]
        articles = fetcher.fetch_source(self._source())
        fetcher._http.get.assert_not_called()
        assert articles == []

    def test_http_error_returns_empty(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.query.return_value = []
        fetcher._http.get.side_effect = httpx.HTTPError("Network error")
        articles = fetcher.fetch_source(self._source())
        assert articles == []

    def test_missing_url_returns_empty(self) -> None:
        fetcher = _make_fetcher()
        articles = fetcher.fetch_source({"id": "test", "rss_url": ""})
        assert articles == []


# ── _persist() ───────────────────────────────────────────────────────────────

class TestPersist:
    def test_empty_list_skips_db(self) -> None:
        fetcher = _make_fetcher()
        count = fetcher._persist([])
        fetcher._client.execute.assert_not_called()
        assert count == 0

    def test_new_article_inserted(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.query.return_value = []
        art = _make_article()
        count = fetcher._persist([art])
        fetcher._client.execute.assert_called_once()
        assert count == 1

    def test_two_articles_two_inserts(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.query.return_value = []
        arts = [_make_article("http://a.com/1", "T1"), _make_article("http://a.com/2", "T2")]
        count = fetcher._persist(arts)
        assert fetcher._client.execute.call_count == 2
        assert count == 2

    def test_duplicate_skipped(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.query.return_value = [("existing_id",)]
        art = _make_article()
        count = fetcher._persist([art])
        fetcher._client.execute.assert_not_called()
        assert count == 0

    def test_db_error_continues(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.query.return_value = []
        fetcher._client.execute.side_effect = Exception("DB error")
        art = _make_article()
        count = fetcher._persist([art])  # should not raise
        assert count == 0


# ── fetch_all() ───────────────────────────────────────────────────────────────

class TestFetchAll:
    def test_returns_all_articles(self) -> None:
        fetcher = _make_fetcher()
        fake = [MagicMock()]
        with patch.object(fetcher, "fetch_source", return_value=fake), \
             patch("time.sleep"):
            result = fetcher.fetch_all()
        # One article per source
        assert len(result) == len(fetcher._sources)

    def test_source_error_continues(self) -> None:
        fetcher = _make_fetcher()
        call_count = 0

        def _side(_):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("network")
            return []

        with patch.object(fetcher, "fetch_source", side_effect=_side), \
             patch("time.sleep"):
            result = fetcher.fetch_all()

        assert isinstance(result, list)
        assert call_count == len(fetcher._sources)

    def test_empty_sources_returns_empty(self) -> None:
        fetcher = _make_fetcher()
        fetcher._sources = []
        with patch("time.sleep"):
            result = fetcher.fetch_all()
        assert result == []
