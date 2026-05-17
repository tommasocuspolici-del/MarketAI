"""News Aggregator — orchestratore del News Engine (Fase 7).

Regola 33: zero articoli simulati — solo feed RSS reali.
Regola 34: pipeline integrata con cache-first.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from engine.news.entity_resolver import EntityResolver
from engine.news.news_classifier import NewsClassifier
from engine.news.news_event_clusterer import NewsEventClusterer
from engine.news.news_signal_generator import NewsSignalGenerator
from engine.news.rss_fetcher import RSSFetcher
from engine.news.schemas import NewsArticle, NewsCluster, NewsSignal
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["NewsAggregator"]

log = get_logger(__name__)


class NewsAggregator:
    """Orchestratore pipeline news: fetch → classify → resolve → cluster → signal.

    Usage::

        agg = NewsAggregator(client=get_duckdb_client())
        signal = agg.run()
    """

    def __init__(self, client: DuckDBClient) -> None:
        self._client = client
        self._fetcher = RSSFetcher(client)
        self._classifier = NewsClassifier()
        self._resolver = EntityResolver()
        self._clusterer = NewsEventClusterer()
        self._signal_gen = NewsSignalGenerator(client)

    def run(self, force_refresh: bool = False) -> NewsSignal:
        """Esegue la pipeline completa e ritorna il segnale news.

        Regola 34: se cache fresca, ritorna segnale cachato senza fetch.
        """
        # 1. Controlla cache segnale (Regola 34)
        if not force_refresh:
            cached = self._signal_gen.read_latest()
            if cached and self._is_fresh(cached.signal_date, ttl_s=1800):
                log.debug("news_aggregator.cache_hit", score=cached.score)
                return cached

        # 2. Fetch articoli RSS
        log.info("news_aggregator.pipeline_start")
        articles = self._fetcher.fetch_all()

        # 3. Classify + entity resolve
        articles = self._enrich(articles)

        # 4. Cluster
        clusters = self._clusterer.cluster(articles)

        # 5. Genera segnale
        signal = self._signal_gen.generate(articles)

        log.info(
            "news_aggregator.pipeline_done",
            articles=len(articles),
            clusters=len(clusters),
            score=round(signal.score, 4),
        )
        return signal

    def fetch_recent(self, hours: int = 24) -> list[NewsArticle]:
        """Legge articoli recenti da DuckDB (Regola 34 — no refetch)."""
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        try:
            rows = self._client.query(
                "SELECT article_id, url, title, source, published_at, category, "
                "summary, tickers_json, sentiment_score, impact_score, "
                "is_duplicate, cluster_id, fetched_at "
                "FROM news_articles WHERE published_at >= ? "
                "ORDER BY published_at DESC LIMIT 200",
                [cutoff],
            )
        except Exception as exc:
            log.warning("news_aggregator.db_read_failed", error=str(exc)[:100])
            return []

        articles = []
        for row in rows or []:
            try:
                from engine.news.schemas import NewsCategory
                import json
                tickers = []
                if row[7]:
                    try:
                        tickers = json.loads(row[7])
                    except Exception:
                        pass
                articles.append(NewsArticle(
                    article_id=row[0],
                    url=row[1],
                    title=row[2],
                    source=row[3],
                    published_at=row[4],
                    category=NewsCategory(row[5]) if row[5] else NewsCategory.UNKNOWN,
                    summary=row[6],
                    tickers=tickers,
                    sentiment_score=float(row[8]) if row[8] is not None else None,
                    impact_score=float(row[9]) if row[9] is not None else 0.5,
                    is_duplicate=bool(row[10]),
                    cluster_id=row[11],
                    fetched_at=row[12],
                ))
            except Exception:
                continue
        return articles

    def _enrich(self, articles: list[NewsArticle]) -> list[NewsArticle]:
        """Applica classificazione e entity resolution."""
        enriched = []
        for art in articles:
            art.category = self._classifier.classify_article(art.title, art.summary)
            art.tickers = self._resolver.extract_tickers(f"{art.title} {art.summary or ''}")
            enriched.append(art)
        return enriched

    def _is_fresh(self, ts: datetime, ttl_s: int) -> bool:
        if ts is None:
            return False
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        age = (datetime.now(UTC) - ts).total_seconds()
        return age < ttl_s
