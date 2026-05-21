"""Tests for engine.ib_forecast.ib_rss_fetcher."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import httpx

from engine.ib_forecast.ib_rss_fetcher import IBRSSFetcher, IB_SOURCES


_RSS_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Fed Speech Title</title>
    <link>https://fed.gov/speech/1</link>
    <pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate>
    <description>Fed speech content here.</description>
  </item>
</channel></rss>"""

_ATOM_XML = """<?xml version="1.0"?>
<feed>
  <entry>
    <title>IMF Blog Post</title>
    <link>https://imf.org/blog/1</link>
    <updated>2024-01-01T00:00:00Z</updated>
    <summary>IMF blog summary.</summary>
  </entry>
</feed>"""

_EMPTY_XML = """<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>"""


def _make_fetcher() -> IBRSSFetcher:
    with patch("httpx.Client"):
        return IBRSSFetcher(client=MagicMock())


def _src() -> dict:
    return {"id": "fed_speeches", "url": "https://fed.gov/rss", "type": "central_bank", "name": "Fed"}


# ── Config ────────────────────────────────────────────────────────────────────

class TestConfig:
    def test_ib_sources_not_empty(self) -> None:
        assert len(IB_SOURCES) >= 1

    def test_each_source_has_required_fields(self) -> None:
        for src in IB_SOURCES:
            assert "id" in src
            assert "url" in src
            assert "type" in src


# ── _is_fresh() ───────────────────────────────────────────────────────────────

class TestIsFresh:
    def test_fresh_returns_true(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.query.return_value = [(datetime.now(UTC),)]
        assert fetcher._is_fresh("fed_speeches") is True

    def test_stale_returns_false(self) -> None:
        fetcher = _make_fetcher()
        old = datetime.now(UTC) - timedelta(seconds=90000)
        fetcher._client.query.return_value = [(old,)]
        assert fetcher._is_fresh("fed_speeches") is False

    def test_no_rows_returns_false(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.query.return_value = []
        assert fetcher._is_fresh("fed_speeches") is False

    def test_none_fetched_at_returns_false(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.query.return_value = [(None,)]
        assert fetcher._is_fresh("fed_speeches") is False

    def test_exception_returns_false(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.query.side_effect = Exception("DB error")
        assert fetcher._is_fresh("fed_speeches") is False

    def test_custom_ttl_respected(self) -> None:
        fetcher = _make_fetcher()
        ts = datetime.now(UTC) - timedelta(seconds=3600)
        fetcher._client.query.return_value = [(ts,)]
        assert fetcher._is_fresh("fed_speeches", ttl_s=7200) is True
        assert fetcher._is_fresh("fed_speeches", ttl_s=1800) is False

    def test_naive_datetime_handled(self) -> None:
        fetcher = _make_fetcher()
        naive = datetime.utcnow()  # noqa: DTZ003
        fetcher._client.query.return_value = [(naive,)]
        result = fetcher._is_fresh("fed_speeches")
        assert isinstance(result, bool)


# ── _parse() ─────────────────────────────────────────────────────────────────

class TestParse:
    def test_rss_feed_parsed(self) -> None:
        fetcher = _make_fetcher()
        reports = fetcher._parse(_RSS_XML, _src())
        assert len(reports) == 1
        assert reports[0]["title"] == "Fed Speech Title"
        assert reports[0]["source"] == "fed_speeches"
        assert reports[0]["report_type"] == "central_bank"

    def test_atom_feed_parsed(self) -> None:
        fetcher = _make_fetcher()
        reports = fetcher._parse(_ATOM_XML, _src())
        assert len(reports) == 1
        assert reports[0]["title"] == "IMF Blog Post"

    def test_empty_feed_returns_empty(self) -> None:
        fetcher = _make_fetcher()
        reports = fetcher._parse(_EMPTY_XML, _src())
        assert reports == []

    def test_missing_date_defaults_utc(self) -> None:
        xml = """<?xml version="1.0"?><rss version="2.0"><channel>
          <item>
            <title>No Date</title>
            <link>https://a.com/1</link>
          </item>
        </channel></rss>"""
        fetcher = _make_fetcher()
        reports = fetcher._parse(xml, _src())
        assert len(reports) == 1
        assert reports[0]["published_at"].tzinfo is not None

    def test_raw_text_truncated_at_2000_chars(self) -> None:
        long_desc = "x" * 3000
        xml = f"""<?xml version="1.0"?><rss version="2.0"><channel>
          <item>
            <title>Long</title>
            <link>https://a.com/1</link>
            <description>{long_desc}</description>
          </item>
        </channel></rss>"""
        fetcher = _make_fetcher()
        reports = fetcher._parse(xml, _src())
        assert len(reports) == 1
        assert len(reports[0]["raw_text"]) <= 2000

    def test_item_without_link_skipped(self) -> None:
        xml = """<?xml version="1.0"?><rss version="2.0"><channel>
          <item><title>Only Title</title></item>
          <item><title>Both</title><link>https://a.com/2</link></item>
        </channel></rss>"""
        fetcher = _make_fetcher()
        reports = fetcher._parse(xml, _src())
        assert len(reports) == 1

    def test_invalid_xml_returns_empty(self) -> None:
        fetcher = _make_fetcher()
        reports = fetcher._parse("not xml!!!", _src())
        assert reports == []

    def test_report_has_report_id_with_source_prefix(self) -> None:
        fetcher = _make_fetcher()
        reports = fetcher._parse(_RSS_XML, _src())
        assert "report_id" in reports[0]
        assert reports[0]["report_id"].startswith("fed_speeches_")

    def test_max_20_items_truncated(self) -> None:
        items = "".join(
            f"<item><title>T{i}</title><link>https://a.com/{i}</link></item>"
            for i in range(25)
        )
        xml = f"<?xml version='1.0'?><rss version='2.0'><channel>{items}</channel></rss>"
        fetcher = _make_fetcher()
        reports = fetcher._parse(xml, _src())
        assert len(reports) <= 20

    def test_report_has_fetched_at(self) -> None:
        fetcher = _make_fetcher()
        reports = fetcher._parse(_RSS_XML, _src())
        assert reports[0]["fetched_at"].tzinfo is not None


# ── _fetch_source() ───────────────────────────────────────────────────────────

class TestFetchSource:
    def test_success_returns_reports(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.query.return_value = []
        mock_resp = MagicMock()
        mock_resp.text = _RSS_XML
        mock_resp.raise_for_status.return_value = None
        fetcher._http.get.return_value = mock_resp

        reports = fetcher._fetch_source(_src())
        assert len(reports) == 1

    def test_http_error_returns_empty(self) -> None:
        fetcher = _make_fetcher()
        fetcher._http.get.side_effect = httpx.HTTPError("timeout")
        reports = fetcher._fetch_source(_src())
        assert reports == []


# ── _persist() ───────────────────────────────────────────────────────────────

class TestPersist:
    def _report(self, report_id: str = "fed_speeches_abc123") -> dict:
        return {
            "report_id": report_id,
            "source": "fed_speeches",
            "report_type": "central_bank",
            "title": "Speech",
            "raw_text": "Content",
            "published_at": datetime.now(UTC),
            "fetched_at": datetime.now(UTC),
        }

    def test_empty_list_skips_db(self) -> None:
        fetcher = _make_fetcher()
        fetcher._persist([])
        fetcher._client.execute.assert_not_called()

    def test_new_report_inserted(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.query.return_value = []
        fetcher._persist([self._report()])
        fetcher._client.execute.assert_called_once()

    def test_duplicate_skipped(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.query.return_value = [("fed_speeches_abc123",)]
        fetcher._persist([self._report()])
        fetcher._client.execute.assert_not_called()

    def test_db_error_silent(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.query.return_value = []
        fetcher._client.execute.side_effect = Exception("DB error")
        fetcher._persist([self._report()])  # should not raise


# ── fetch_all() ───────────────────────────────────────────────────────────────

class TestFetchAll:
    def test_fresh_source_skipped(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.query.return_value = [(datetime.now(UTC),)]

        with patch("time.sleep"):
            result = fetcher.fetch_all()

        fetcher._http.get.assert_not_called()
        assert result == []

    def test_returns_list_with_results(self) -> None:
        fetcher = _make_fetcher()
        with patch.object(fetcher, "_is_fresh", return_value=False), \
             patch.object(fetcher, "_fetch_source", return_value=[{"title": "X"}]), \
             patch("time.sleep"):
            result = fetcher.fetch_all()
        assert isinstance(result, list)
        assert len(result) == len(IB_SOURCES)

    def test_source_error_continues(self) -> None:
        fetcher = _make_fetcher()
        call_count = 0

        def _side(_):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("network")
            return []

        with patch.object(fetcher, "_is_fresh", return_value=False), \
             patch.object(fetcher, "_fetch_source", side_effect=_side), \
             patch("time.sleep"):
            result = fetcher.fetch_all()

        assert isinstance(result, list)
        assert call_count == len(IB_SOURCES)
