"""RSS Fetcher — 6 fonti configurate in config/news_sources.yaml.

Regola 33: solo feed RSS reali, zero articoli simulati.
Regola 34: articoli cachati in news_articles (TTL: news_rss = 1800s).
Dedup: SHA256 su URL+titolo prima di scrivere in DuckDB.
"""
from __future__ import annotations

import hashlib
import pathlib
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING

import httpx
import yaml

from engine.news.schemas import NewsArticle, NewsCategory
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["RSSFetcher"]

log = get_logger(__name__)

_CONFIG_PATH = pathlib.Path(__file__).parent.parent.parent / "config" / "news_sources.yaml"
_TIMEOUT = 15.0
_DELAY_S = 0.5


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _parse_rss_entry(entry: dict, source_id: str) -> NewsArticle | None:
    """Estrae un NewsArticle da un entry feedparser."""
    title = (entry.get("title") or "").strip()
    url = entry.get("link") or entry.get("id") or ""
    if not title or not url:
        return None

    # Published date
    pub_raw = entry.get("published") or entry.get("updated") or ""
    try:
        published_at = parsedate_to_datetime(pub_raw)
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=UTC)
    except Exception:
        published_at = datetime.now(UTC)

    summary = (entry.get("summary") or entry.get("description") or "").strip()
    content_hash = _sha256(url + title)
    article_id = f"{source_id}_{content_hash}"

    return NewsArticle(
        article_id=article_id,
        url=url,
        title=title,
        source=source_id,
        published_at=published_at,
        summary=summary[:500] if summary else None,
        content_hash=content_hash,
        fetched_at=datetime.now(UTC),
    )


class RSSFetcher:
    """Fetcher RSS per 6 fonti configurate.

    Args:
        client: DuckDBClient per cache-first (Regola 34).

    Usage::

        fetcher = RSSFetcher(client=get_duckdb_client())
        articles = fetcher.fetch_all()
    """

    def __init__(self, client: DuckDBClient) -> None:
        self._client = client
        self._http = httpx.Client(timeout=_TIMEOUT, follow_redirects=True)
        self._sources = self._load_sources()

    def _load_sources(self) -> list[dict]:
        if not _CONFIG_PATH.exists():
            return _default_sources()
        with _CONFIG_PATH.open(encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("news_sources", _default_sources())

    def fetch_all(self) -> list[NewsArticle]:
        """Scarica e salva articoli da tutte le fonti configurate.

        Regola 34: controlla TTL prima di fare richiesta HTTP.
        """
        all_articles: list[NewsArticle] = []
        for src in self._sources:
            try:
                articles = self.fetch_source(src)
                all_articles.extend(articles)
                time.sleep(_DELAY_S)
            except Exception as exc:
                log.warning("rss_fetcher.source_failed", source=src.get("id"), error=str(exc)[:200])

        log.info("rss_fetcher.all_done", total=len(all_articles))
        return all_articles

    def fetch_source(self, source: dict) -> list[NewsArticle]:
        """Scarica e persiste articoli da una singola sorgente RSS."""
        source_id = source.get("id", "unknown")
        url = source.get("rss_url", "")
        if not url:
            return []

        # Regola 34: controlla se abbiamo dati freschi
        if self._has_fresh_cache(source_id, source.get("fetch_interval_seconds", 1800)):
            log.debug("rss_fetcher.cache_hit", source=source_id)
            return []

        log.info("rss_fetcher.fetching", source=source_id, url=url)
        try:
            resp = self._http.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("rss_fetcher.http_error", source=source_id, error=str(exc)[:100])
            return []

        articles = self._parse_feed(resp.text, source_id, source)
        new_count = self._persist(articles)
        log.info("rss_fetcher.source_done", source=source_id, fetched=len(articles), new=new_count)
        return articles

    def _parse_feed(self, xml_text: str, source_id: str, source: dict) -> list[NewsArticle]:
        """Parsa XML RSS/Atom senza dipendenze esterne (parser semplice)."""
        articles = []
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml_text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            # RSS 2.0
            items = root.findall(".//item")
            if not items:
                # Atom
                items = root.findall(".//atom:entry", ns) + root.findall(".//entry")

            for item in items[:50]:  # Max 50 per feed
                title_el = item.find("title")
                link_el = item.find("link")
                pubdate_el = item.find("pubDate") or item.find("published")

                title = (title_el.text or "").strip() if title_el is not None else ""
                link = ""
                if link_el is not None:
                    link = link_el.text or link_el.get("href") or ""
                link = link.strip()

                if not title or not link:
                    continue

                pub_raw = (pubdate_el.text or "").strip() if pubdate_el is not None else ""
                try:
                    published_at = parsedate_to_datetime(pub_raw)
                    if published_at.tzinfo is None:
                        published_at = published_at.replace(tzinfo=UTC)
                except Exception:
                    published_at = datetime.now(UTC)

                desc_el = item.find("description") or item.find("summary")
                summary = (desc_el.text or "").strip()[:500] if desc_el is not None else None

                content_hash = _sha256(link + title)
                articles.append(NewsArticle(
                    article_id=f"{source_id}_{content_hash}",
                    url=link,
                    title=title,
                    source=source_id,
                    published_at=published_at,
                    summary=summary,
                    content_hash=content_hash,
                    fetched_at=datetime.now(UTC),
                ))
        except Exception as exc:
            log.warning("rss_fetcher.parse_error", source=source_id, error=str(exc)[:100])
        return articles

    def _has_fresh_cache(self, source_id: str, ttl_seconds: int) -> bool:
        """True se abbiamo articoli freschi per questa sorgente (Regola 34)."""
        try:
            rows = self._client.query(
                "SELECT fetched_at FROM news_articles WHERE source=? "
                "ORDER BY fetched_at DESC LIMIT 1",
                [source_id],
            )
            if not rows or not rows[0][0]:
                return False
            fetched_at = rows[0][0]
            if hasattr(fetched_at, "tzinfo") and fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=UTC)
            age_s = (datetime.now(UTC) - fetched_at).total_seconds()
            return age_s < ttl_seconds
        except Exception:
            return False

    def _persist(self, articles: list[NewsArticle]) -> int:
        """Salva articoli non duplicati in news_articles. Ritorna count nuovi."""
        new_count = 0
        for art in articles:
            try:
                # Dedup via content_hash
                existing = self._client.query(
                    "SELECT article_id FROM news_articles WHERE article_id=? LIMIT 1",
                    [art.article_id],
                )
                if existing:
                    continue

                self._client.execute(
                    """
                    INSERT INTO news_articles
                        (article_id, url, title, source, published_at, category,
                         summary, is_duplicate, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, FALSE, ?)
                    ON CONFLICT (article_id) DO NOTHING
                    """,
                    [
                        art.article_id, art.url, art.title, art.source,
                        art.published_at, art.category.value,
                        art.summary, art.fetched_at,
                    ],
                )
                new_count += 1
            except Exception as exc:
                log.debug("rss_fetcher.persist_skip", article_id=art.article_id, error=str(exc)[:80])

        return new_count

    def __del__(self) -> None:
        try:
            self._http.close()
        except Exception:
            pass


def _default_sources() -> list[dict]:
    """Fonti RSS di default se config/news_sources.yaml non trovato."""
    return [
        {"id": "reuters",        "rss_url": "https://feeds.reuters.com/reuters/businessNews",                          "fetch_interval_seconds": 1800, "credibility_weight": 0.95},
        {"id": "cnbc",           "rss_url": "https://search.cnbc.com/rs/search/combinedcombined/view/rss/section/news","fetch_interval_seconds": 1800, "credibility_weight": 0.85},
        {"id": "financial_times","rss_url": "https://www.ft.com/?format=rss",                                          "fetch_interval_seconds": 3600, "credibility_weight": 0.95},
        {"id": "seeking_alpha",  "rss_url": "https://seekingalpha.com/market_currents.xml",                            "fetch_interval_seconds": 1800, "credibility_weight": 0.75},
        {"id": "nasdaq_news",    "rss_url": "https://www.nasdaq.com/feed/rssoutbound?category=Markets",                "fetch_interval_seconds": 1800, "credibility_weight": 0.80},
        {"id": "finviz",         "rss_url": "https://finviz.com/news.ashx?v=2",                                        "fetch_interval_seconds": 1800, "credibility_weight": 0.70},
    ]
