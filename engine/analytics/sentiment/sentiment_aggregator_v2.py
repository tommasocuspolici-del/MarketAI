"""SentimentAggregatorV2 — orchestrates the full sentiment v2 pipeline (QC-enhanced).

Pipeline:
  1. Annotate articles with source credibility weights
  2. SourceDeduplicator: N articles → M unique events (M ≤ N)
  3. FinBERTScorer.score_batch() on deduplicated event titles
  4. EntityExtractor: per-ticker/sector scores
  5. Build AggregatedSentimentV2 with quality_flag
  6. Publish to Signal Bus with ic_estimate (QC-1)
  7. Update AlphaDecayMonitor (QC-2)

Invariant (Rule 26 extended):
  n_unique_events < 3 → quality_flag = "insufficient_data" + warning

Quality flag propagation: if AlphaDecayMonitor reports IC < IC_MIN → "low_ic".
"""
from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from engine.analytics.sentiment.entity_extractor import EntityExtractor
from engine.analytics.sentiment.finbert_scorer import FinBERTScorer
from engine.analytics.sentiment.schemas import AggregatedSentimentV2
from engine.analytics.sentiment.source_credibility_tracker import SourceCredibilityTracker
from engine.analytics.sentiment.source_deduplicator import SourceDeduplicator
from shared.alpha_decay_monitor import AlphaDecayMonitor, IC_MIN_THRESHOLD
from shared.logger import get_logger
from shared.signal_bus import get_signal_bus
from shared.signal_types import Signal

__version__ = "10.0.0"

__all__ = ["SentimentAggregatorV2"]

log = get_logger(__name__)

_MIN_UNIQUE_EVENTS = 3    # Rule 26 threshold
_SIGNAL_NAME       = "sentiment_composite"


class SentimentAggregatorV2:
    """Orchestrates the complete Sentiment Engine v2 pipeline.

    Args:
        decay_monitor:    AlphaDecayMonitor for IC tracking (QC-2).
        publish_to_bus:   Whether to publish result to SignalBus (default True).
    """

    def __init__(
        self,
        decay_monitor:  AlphaDecayMonitor,
        publish_to_bus: bool = True,
    ) -> None:
        self._monitor     = decay_monitor
        self._publish     = publish_to_bus
        self._scorer      = FinBERTScorer()
        self._dedup       = SourceDeduplicator()
        self._extractor   = EntityExtractor()
        self._credibility = SourceCredibilityTracker()

    def aggregate(
        self,
        articles: list[dict],
        # Each dict: {"title": str, "source": str, "summary"?: str}
        forward_return: float | None = None,    # For IC update (QC-2)
    ) -> AggregatedSentimentV2:
        """Run full pipeline on a batch of articles.

        Args:
            articles:       List of article dicts (title + source required).
            forward_return: If provided, updates AlphaDecayMonitor after scoring.

        Returns:
            AggregatedSentimentV2 with quality_flag and ic_estimate.
        """
        n_articles = len(articles)
        if n_articles == 0:
            return self._empty_result()

        # Step 1 — Annotate with credibility
        articles = self._credibility.annotate_articles(articles)

        # Step 2 — Deduplicate
        events = self._dedup.deduplicate(articles)
        n_unique = len(events)

        quality_flag = "ok"
        if n_unique < _MIN_UNIQUE_EVENTS:
            quality_flag = "insufficient_data"
            log.warning(
                "sentiment_v2.insufficient_events",
                n_unique=n_unique,
                required=_MIN_UNIQUE_EVENTS,
            )

        # Step 3 — Score events with FinBERT/VADER
        event_titles = [f"cluster_{e.cluster_id}" if not e.theme_keywords
                        else " ".join(e.theme_keywords[:3])
                        for e in events]
        # Use article titles directly for scoring (more informative than keywords)
        titles_for_scoring = [articles[i]["title"] if i < len(articles) else ""
                              for i in range(len(events))]
        labels = self._scorer.score_batch(titles_for_scoring)

        # Step 4 — Weighted composite
        if labels:
            scores  = np.array([l.score for l in labels], dtype=np.float64)
            weights = np.array([e.article_count for e in events], dtype=np.float64)
            weights /= weights.sum()
            composite = float(np.clip(np.dot(scores, weights), -1.0, 1.0))
            confidence = float(np.mean([l.confidence for l in labels]))
        else:
            composite  = 0.0
            confidence = 0.0

        # Step 5 — Entity extraction (on all article titles)
        entity_scores: dict[str, float] = {}
        for art in articles:
            entities = self._extractor.extract(art["title"])
            for e in entities:
                if e.entity_type == "ticker":
                    entity_scores.setdefault(e.entity, []).append(art.get("score", composite))

        entity_means = {t: float(np.mean(s)) for t, s in entity_scores.items()}

        # Step 6 — IC tracking (QC-2)
        ic_estimate: float | None = None
        if forward_return is not None:
            self._monitor.update(
                signal_name    = _SIGNAL_NAME,
                signal_value   = composite,
                forward_return = forward_return,
            )
            ic, ic_flag = self._monitor.check_decay(_SIGNAL_NAME)
            ic_estimate = ic
            if ic_flag == "low_ic" and quality_flag == "ok":
                quality_flag = "low_ic"

        model_used = self._scorer.model_name
        result = AggregatedSentimentV2(
            composite_score = round(composite, 4),
            confidence      = round(confidence, 4),
            n_articles      = n_articles,
            n_unique_events = n_unique,
            quality_flag    = quality_flag,
            ic_estimate     = ic_estimate,
            model_used      = model_used,
            entity_scores   = entity_means,
            computed_at     = datetime.now(UTC),
        )

        # Step 7 — Publish to Signal Bus (QC-1)
        if self._publish:
            signal = Signal(
                name          = _SIGNAL_NAME,
                value         = composite,
                confidence    = confidence,
                source_module = __name__,
                ic_estimate   = ic_estimate,
                quality_flag  = quality_flag,  # type: ignore[arg-type]
                metadata      = {
                    "n_articles":     n_articles,
                    "n_unique_events": n_unique,
                    "model":          model_used,
                },
            )
            get_signal_bus().publish(signal)
            log.info(
                "sentiment_v2.published",
                score=round(composite, 4),
                quality=quality_flag,
                n_events=n_unique,
                model=model_used,
            )

        return result

    @staticmethod
    def _empty_result() -> AggregatedSentimentV2:
        return AggregatedSentimentV2(
            composite_score = 0.0,
            confidence      = 0.0,
            n_articles      = 0,
            n_unique_events = 0,
            quality_flag    = "insufficient_data",
            ic_estimate     = None,
            model_used      = "none",
            computed_at     = datetime.now(UTC),
        )
