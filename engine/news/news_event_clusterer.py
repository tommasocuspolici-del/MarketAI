"""News Event Clusterer — TF-IDF (500 features) + DBSCAN (eps=0.25).

Raggruppa articoli sullo stesso evento per ridurre rumore nel segnale news.
Regola 33: clustering su testo reale (nessun seed/mock).
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from engine.news.schemas import NewsArticle, NewsCategory, NewsCluster
from shared.logger import get_logger

if TYPE_CHECKING:
    pass

__version__ = "1.0.0"
__all__ = ["NewsEventClusterer"]

log = get_logger(__name__)


class NewsEventClusterer:
    """TF-IDF + DBSCAN per raggruppamento eventi news.

    Richiede scikit-learn (già dipendenza del progetto).

    Args:
        max_features: Numero massimo di feature TF-IDF (default: 500).
        eps:          Distanza DBSCAN (default: 0.25).
        min_samples:  Campioni minimi per cluster (default: 2).

    Usage::

        clusterer = NewsEventClusterer()
        clusters = clusterer.cluster(articles)
    """

    def __init__(
        self,
        max_features: int = 500,
        eps: float = 0.25,
        min_samples: int = 2,
    ) -> None:
        self._max_features = max_features
        self._eps = eps
        self._min_samples = min_samples

    def cluster(self, articles: list[NewsArticle]) -> list[NewsCluster]:
        """Raggruppa articoli per evento.

        Args:
            articles: Lista di NewsArticle da raggruppare.

        Returns:
            Lista di NewsCluster (articoli noise = cluster singoli).
        """
        if len(articles) < 2:
            return [self._singleton_cluster(a) for a in articles]

        try:
            from sklearn.cluster import DBSCAN
            from sklearn.feature_extraction.text import TfidfVectorizer
        except ImportError:
            log.warning("news_clusterer.sklearn_not_available — ritorno cluster singoli")
            return [self._singleton_cluster(a) for a in articles]

        texts = [f"{a.title} {a.summary or ''}" for a in articles]

        try:
            vectorizer = TfidfVectorizer(
                max_features=self._max_features,
                stop_words="english",
                ngram_range=(1, 2),
                min_df=1,
            )
            X = vectorizer.fit_transform(texts)

            db = DBSCAN(
                eps=self._eps,
                min_samples=self._min_samples,
                metric="cosine",
                n_jobs=-1,
            )
            labels = db.fit_predict(X)
        except Exception as exc:
            log.warning("news_clusterer.dbscan_failed", error=str(exc)[:200])
            return [self._singleton_cluster(a) for a in articles]

        # Raggruppa per label
        groups: dict[int, list[NewsArticle]] = {}
        for i, label in enumerate(labels):
            groups.setdefault(label, []).append(articles[i])

        clusters: list[NewsCluster] = []
        for label, group in groups.items():
            if label == -1:
                # Noise: ogni articolo è un cluster singolo
                clusters.extend(self._singleton_cluster(a) for a in group)
            else:
                clusters.append(self._make_cluster(group))

        log.info(
            "news_clusterer.done",
            articles=len(articles),
            clusters=len(clusters),
            noise=sum(1 for l in labels if l == -1),
        )
        return clusters

    def _make_cluster(self, articles: list[NewsArticle]) -> NewsCluster:
        """Crea un cluster da un gruppo di articoli."""
        sorted_articles = sorted(articles, key=lambda a: a.published_at, reverse=True)
        headline = sorted_articles[0].title

        tickers: list[str] = []
        seen: set[str] = set()
        for a in articles:
            for t in a.tickers:
                if t not in seen:
                    tickers.append(t)
                    seen.add(t)

        categories = [a.category for a in articles]
        dominant_cat = max(set(categories), key=categories.count)

        scores = [a.sentiment_score for a in articles if a.sentiment_score is not None]
        avg_sentiment = sum(scores) / len(scores) if scores else None

        cluster_id = hashlib.sha256(headline.encode()).hexdigest()[:16]

        return NewsCluster(
            cluster_id=cluster_id,
            headline=headline,
            articles=sorted_articles,
            tickers=tickers[:10],
            category=dominant_cat,
            sentiment_score=avg_sentiment,
            impact_score=sum(a.impact_score for a in articles) / len(articles),
            first_seen_at=min(a.published_at for a in articles),
            last_updated_at=datetime.now(UTC),
            source_count=len({a.source for a in articles}),
        )

    def _singleton_cluster(self, article: NewsArticle) -> NewsCluster:
        cluster_id = f"s_{article.content_hash or article.article_id[:16]}"
        return NewsCluster(
            cluster_id=cluster_id,
            headline=article.title,
            articles=[article],
            tickers=article.tickers,
            category=article.category,
            sentiment_score=article.sentiment_score,
            impact_score=article.impact_score,
            first_seen_at=article.published_at,
            last_updated_at=datetime.now(UTC),
            source_count=1,
        )
