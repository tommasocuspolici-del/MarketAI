"""IB RSS Fetcher — feed pubblici Investment Bank e banche centrali.

Regola 33: zero previsioni simulate.
Regola 34: TTL ib_forecast = 86400s.
"""
from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any
import xml.etree.ElementTree as ET

import httpx

from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["IBRSSFetcher"]

log = get_logger(__name__)

_TIMEOUT = 20.0
_DELAY_S = 1.0

# Feed RSS/Atom pubblici da istituzioni finanziarie
IB_SOURCES: list[dict[str, str]] = [
    {
        "id": "fed_speeches",
        "url": "https://www.federalreserve.gov/feeds/speeches.xml",
        "type": "central_bank",
        "name": "Federal Reserve Speeches",
    },
    {
        "id": "fed_press",
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "type": "central_bank",
        "name": "Federal Reserve Press Releases",
    },
    {
        "id": "imf_blog",
        "url": "https://www.imf.org/en/Blogs/rss",
        "type": "institution",
        "name": "IMF Blog",
    },
    {
        "id": "world_bank_blog",
        "url": "https://blogs.worldbank.org/feed",
        "type": "institution",
        "name": "World Bank Blogs",
    },
    {
        "id": "bis_speeches",
        "url": "https://www.bis.org/rss/speeches.rss",
        "type": "central_bank",
        "name": "BIS Speeches",
    },
    {
        "id": "ecb_press",
        "url": "https://www.ecb.europa.eu/rss/press.html",
        "type": "central_bank",
        "name": "ECB Press Releases",
    },
]


class IBRSSFetcher:
    """Fetcher RSS per report pubblici IB, Fed, IMF, BIS.

    Args:
        client: DuckDBClient per cache-first (Regola 34).
    """

    def __init__(self, client: DuckDBClient) -> None:
        self._client = client
        self._http = httpx.Client(timeout=_TIMEOUT, follow_redirects=True)

    def fetch_all(self) -> list[dict[str, Any]]:
        """Scarica report da tutte le sorgenti IB configurate."""
        all_reports: list[dict[str, Any]] = []
        for src in IB_SOURCES:
            try:
                if self._is_fresh(src["id"]):
                    log.debug("ib_rss.cache_hit", source=src["id"])
                    continue
                reports = self._fetch_source(src)
                all_reports.extend(reports)
                time.sleep(_DELAY_S)
            except Exception as exc:
                log.warning("ib_rss.source_failed", source=src["id"], error=str(exc)[:100])

        log.info("ib_rss.all_done", total=len(all_reports))
        return all_reports

    def _fetch_source(self, src: dict[str, str]) -> list[dict[str, Any]]:
        """Scarica e persiste report da una sorgente."""
        source_id = src["id"]
        url = src["url"]

        try:
            resp = self._http.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("ib_rss.http_error", source=source_id, error=str(exc)[:100])
            return []

        reports = self._parse(resp.text, src)
        self._persist(reports)
        log.info("ib_rss.source_done", source=source_id, count=len(reports))
        return reports

    def _parse(self, xml_text: str, src: dict[str, str]) -> list[dict[str, Any]]:
        """Parsa feed RSS/Atom e ritorna lista di report dict."""
        reports: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        try:
            root = ET.fromstring(xml_text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//item") or root.findall(".//atom:entry", ns) or root.findall(".//entry")

            for item in items[:20]:
                title_el = item.find("title")
                link_el = item.find("link")
                desc_el = item.find("description") or item.find("summary") or item.find("{http://www.w3.org/2005/Atom}summary")
                pub_el = item.find("pubDate") or item.find("published") or item.find("{http://www.w3.org/2005/Atom}published")

                title = (title_el.text or "").strip() if title_el is not None else ""
                link = ""
                if link_el is not None:
                    link = link_el.text or link_el.get("href") or ""
                link = link.strip()

                if not title or not link:
                    continue

                pub_raw = (pub_el.text or "").strip() if pub_el is not None else ""
                try:
                    published_at = parsedate_to_datetime(pub_raw)
                    if published_at.tzinfo is None:
                        published_at = published_at.replace(tzinfo=UTC)
                except Exception:
                    published_at = now

                raw_text = (desc_el.text or "").strip()[:2000] if desc_el is not None else ""
                report_id = f"{src['id']}_{hashlib.sha256((link + title).encode()).hexdigest()[:16]}"

                reports.append({
                    "report_id": report_id,
                    "source": src["id"],
                    "report_type": src.get("type", "rss"),
                    "title": title,
                    "raw_text": raw_text,
                    "published_at": published_at,
                    "fetched_at": now,
                })
        except Exception as exc:
            log.warning("ib_rss.parse_error", source=src.get("id"), error=str(exc)[:100])
        return reports

    def _is_fresh(self, source_id: str, ttl_s: int = 86400) -> bool:
        """Regola 34: controlla TTL prima di fetch."""
        try:
            rows = self._client.query(
                "SELECT fetched_at FROM ib_reports WHERE source=? ORDER BY fetched_at DESC LIMIT 1",
                [source_id],
            )
            if not rows or not rows[0][0]:
                return False
            fetched_at = rows[0][0]
            if hasattr(fetched_at, "tzinfo") and fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=UTC)
            return bool((datetime.now(UTC) - fetched_at).total_seconds() < ttl_s)
        except Exception:
            return False

    def _persist(self, reports: list[dict[str, Any]]) -> None:
        """Salva in ib_reports (Regola 34)."""
        for rep in reports:
            try:
                existing = self._client.query(
                    "SELECT report_id FROM ib_reports WHERE report_id=? LIMIT 1",
                    [rep["report_id"]],
                )
                if existing:
                    continue
                self._client.execute(
                    """
                    INSERT INTO ib_reports (report_id, source, report_type, title, raw_text, published_at, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (report_id) DO NOTHING
                    """,
                    [rep["report_id"], rep["source"], rep["report_type"],
                     rep["title"], rep["raw_text"], rep["published_at"], rep["fetched_at"]],
                )
            except Exception as exc:
                log.debug("ib_rss.persist_skip", error=str(exc)[:80])

    def __del__(self) -> None:
        try:
            self._http.close()
        except Exception:
            pass
