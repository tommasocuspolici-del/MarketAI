"""SourceDeduplicator — same news event from N sources = 1 data point (QC).

Problem: "Fed raises rates" generates 50 articles across 10 sources in 2 hours.
Counting 50 signals amplifies a single event artificially.
This deduplicator reduces it to 1 event with high confidence.

Algorithm:
  1. TF-IDF embedding of headlines (scikit-learn, max 500 features)
  2. DBSCAN clustering (ε=0.25, min_samples=2) on cosine distance matrix
  3. Each cluster = 1 unique event; noise points = unclustered singletons
  4. Event score = credibility-weighted average of article scores
  5. Top-5 TF-IDF keywords extracted per cluster for transparency

Rule 26 (extended): sentiment from < 3 UNIQUE EVENTS → quality_flag = "insufficient_data".
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_distances

from shared.logger import get_logger

__version__ = "10.0.0"

__all__ = ["DeduplicatedEvent", "SourceDeduplicator"]

log = get_logger(__name__)

_TFIDF_MAX_FEATURES = 500
_DBSCAN_EPS         = 0.25
_DBSCAN_MIN_SAMPLES = 2


@dataclass
class DeduplicatedEvent:
    cluster_id:     int
    article_count:  int
    source_count:   int
    avg_score:      float           # unweighted mean of article scores
    weighted_score: float           # credibility-weighted score  [-1, 1]
    theme_keywords: list[str] = field(default_factory=list)


class SourceDeduplicator:
    """Deduplicate news articles into unique events.

    Args:
        eps:         DBSCAN epsilon (cosine distance threshold, default 0.25).
        min_samples: Minimum articles to form a cluster (default 2).
    """

    def __init__(
        self,
        eps:         float = _DBSCAN_EPS,
        min_samples: int   = _DBSCAN_MIN_SAMPLES,
    ) -> None:
        self._eps         = eps
        self._min_samples = min_samples

    def deduplicate(
        self,
        articles: list[dict],
        # Each dict: {"title": str, "score": float, "source": str, "credibility": float}
    ) -> list[DeduplicatedEvent]:
        """Deduplicate articles into unique events.

        Returns an empty list for empty input. Single-article input returns
        one event with cluster_id=0.
        """
        if not articles:
            return []

        if len(articles) == 1:
            a = articles[0]
            score = float(a.get("score", 0.0))
            return [DeduplicatedEvent(
                cluster_id    = 0,
                article_count = 1,
                source_count  = 1,
                avg_score     = score,
                weighted_score= float(np.clip(score, -1.0, 1.0)),
                theme_keywords= [],
            )]

        texts = [a["title"] for a in articles]

        # TF-IDF embedding
        try:
            tfidf       = TfidfVectorizer(max_features=_TFIDF_MAX_FEATURES, stop_words="english")
            X           = tfidf.fit_transform(texts).toarray()
            feat_names  = tfidf.get_feature_names_out()
        except Exception as exc:
            log.error("deduplicator.tfidf_failed", error=str(exc))
            return self._fallback_no_dedup(articles)

        # DBSCAN on cosine distance
        dist = cosine_distances(X)
        labels = DBSCAN(
            eps         = self._eps,
            min_samples = self._min_samples,
            metric      = "precomputed",
        ).fit_predict(dist)

        events: list[DeduplicatedEvent] = []
        for cid in sorted(set(labels)):
            idx      = [i for i, l in enumerate(labels) if l == cid]
            members  = [articles[i] for i in idx]

            scores   = np.array([a.get("score", 0.0)          for a in members], dtype=np.float64)
            weights  = np.array([a.get("credibility", 1.0)   for a in members], dtype=np.float64)
            w_sum    = weights.sum()
            if w_sum > 0:
                weights /= w_sum

            weighted_score = float(np.clip(np.dot(scores, weights), -1.0, 1.0))
            avg_score      = float(np.mean(scores))
            sources        = {a["source"] for a in members}

            # Top-5 cluster keywords
            cluster_tfidf = X[idx].mean(axis=0)
            top_idx       = cluster_tfidf.argsort()[-5:][::-1]
            keywords      = [feat_names[i] for i in top_idx if cluster_tfidf[i] > 0]

            events.append(DeduplicatedEvent(
                cluster_id    = int(cid),
                article_count = len(idx),
                source_count  = len(sources),
                avg_score     = round(avg_score, 4),
                weighted_score= round(weighted_score, 4),
                theme_keywords= keywords,
            ))

        log.info(
            "deduplicator.done",
            n_articles=len(articles),
            n_events=len(events),
            compression=round(len(articles) / max(len(events), 1), 1),
        )
        return events

    @staticmethod
    def _fallback_no_dedup(articles: list[dict]) -> list[DeduplicatedEvent]:
        """Return one event per article (no deduplication) as a safe fallback."""
        return [
            DeduplicatedEvent(
                cluster_id    = i,
                article_count = 1,
                source_count  = 1,
                avg_score     = float(a.get("score", 0.0)),
                weighted_score= float(np.clip(a.get("score", 0.0), -1.0, 1.0)),
            )
            for i, a in enumerate(articles)
        ]
