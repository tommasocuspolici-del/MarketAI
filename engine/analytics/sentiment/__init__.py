"""Sentiment analytics — multi-source aggregation + contrarian signals."""
from __future__ import annotations

from engine.analytics.sentiment.aggregator import (
    CompositeSentiment,
    SentimentAggregator,
)
from engine.analytics.sentiment.signal_model import (
    SentimentSignal,
    SentimentSource,
)

__version__ = "6.0.0"

__all__ = [
    "CompositeSentiment",
    "SentimentAggregator",
    "SentimentSignal",
    "SentimentSource",
]
