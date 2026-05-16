"""Sentiment v2 data schemas — typed dataclasses for all v2 pipeline outputs."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

__version__ = "10.0.0"

__all__ = [
    "ArticleInput",
    "ScoredArticle",
    "EntitySentiment",
    "SentimentVelocitySnapshot",
    "SourceCredibilityEntry",
    "AggregatedSentimentV2",
]


@dataclass
class ArticleInput:
    """Raw article before scoring."""
    title:       str
    source:      str
    published_at: datetime | None = None
    summary:     str = ""


@dataclass
class ScoredArticle:
    """Article after FinBERT (or VADER) scoring."""
    title:        str
    source:       str
    score:        float          # [-1, 1]
    confidence:   float          # [0, 1]
    model_used:   str            # "finbert" | "vader"
    credibility:  float = 1.0   # Source credibility weight


@dataclass
class EntitySentiment:
    """Per-entity (ticker/sector) sentiment extracted from articles."""
    entity:       str            # Ticker or sector name
    entity_type:  str            # "ticker" | "sector" | "index"
    score:        float          # [-1, 1]
    article_count: int
    confidence:   float


@dataclass
class SentimentVelocitySnapshot:
    """First derivative of sentiment over time."""
    ticker:       str | None     # None = market-wide
    velocity_1d:  float | None   # Change vs yesterday
    velocity_5d:  float | None   # Change vs last week
    velocity_20d: float | None   # Change vs last month
    acceleration: float | None   # Second derivative (change of change)
    regime:       str            # 'improving' | 'deteriorating' | 'stable' | 'reversing'


@dataclass
class SourceCredibilityEntry:
    """Dynamic credibility weight for a news source."""
    source:          str
    weight:          float          # [0, 1] — updated weekly
    accuracy_score:  float          # Historical IC vs forward returns
    sample_size:     int
    last_updated:    datetime


@dataclass
class AggregatedSentimentV2:
    """Final output of SentimentAggregatorV2."""
    composite_score:  float          # [-1, 1] weighted composite
    confidence:       float          # [0, 1]
    n_articles:       int            # Raw article count
    n_unique_events:  int            # After deduplication
    quality_flag:     str            # "ok" | "insufficient_data" | "low_ic"
    ic_estimate:      float | None
    model_used:       str            # "finbert" | "vader"
    entity_scores:    dict[str, float] = field(default_factory=dict)
    computed_at:      datetime | None  = None
