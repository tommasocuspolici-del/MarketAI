"""Schema dataclass per il News Engine (Fase 7)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

__version__ = "1.0.0"
__all__ = [
    "NewsCategory", "NewsSentiment", "NewsArticle",
    "NewsCluster", "NewsSignal",
]


class NewsCategory(str, Enum):
    EARNINGS       = "earnings"
    MACRO          = "macro"
    GEOPOLITICS    = "geopolitics"
    CENTRAL_BANK   = "central_bank"
    EQUITY         = "equity"
    COMMODITIES    = "commodities"
    CRYPTO         = "crypto"
    UNKNOWN        = "unknown"


class NewsSentiment(str, Enum):
    BULLISH        = "bullish"
    BEARISH        = "bearish"
    NEUTRAL        = "neutral"


@dataclass
class NewsArticle:
    """Articolo di notizie normalizzato.

    Regola 33: source è sempre valorizzato (non NULL, non hardcoded).
    """
    article_id:     str
    url:            str
    title:          str
    source:         str                         # mai NULL — Regola 33
    published_at:   datetime
    category:       NewsCategory = NewsCategory.UNKNOWN
    summary:        str | None = None
    tickers:        list[str] = field(default_factory=list)
    sentiment_score: float | None = None        # [-1, +1]
    impact_score:   float = 0.5                 # [0, 1]
    is_duplicate:   bool = False
    cluster_id:     str | None = None
    content_hash:   str | None = None           # SHA256 per dedup
    fetched_at:     datetime | None = None
    data_quality:   str = "ok"                  # 'ok'|'low'|'duplicate'


@dataclass
class NewsCluster:
    """Gruppo di articoli su stesso evento (TF-IDF + DBSCAN)."""
    cluster_id:     str
    headline:       str                         # Titolo rappresentativo
    articles:       list[NewsArticle] = field(default_factory=list)
    tickers:        list[str] = field(default_factory=list)
    category:       NewsCategory = NewsCategory.UNKNOWN
    sentiment_score: float | None = None
    impact_score:   float = 0.5
    first_seen_at:  datetime | None = None
    last_updated_at: datetime | None = None
    source_count:   int = 0


@dataclass
class NewsSignal:
    """Segnale aggregato dal news engine per Composite Signal v3.

    Regola 33: tutti i valori provengono da articoli reali.
    """
    signal_date:    datetime
    score:          float           # [-1, +1]
    article_count:  int
    cluster_count:  int
    bullish_count:  int
    bearish_count:  int
    neutral_count:  int
    top_tickers:    list[str] = field(default_factory=list)
    top_categories: list[str] = field(default_factory=list)
    data_quality:   str = "ok"
    source:         str = "news_engine"
