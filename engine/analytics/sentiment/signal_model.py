"""Sentiment data model — single reading from one source."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

__version__ = "6.0.0"

__all__ = ["SentimentSignal", "SentimentSource"]


class SentimentSource(StrEnum):
    """The 8 sentiment sources tracked by the engine."""

    CNN_FEAR_GREED = "cnn_fear_greed"
    CRYPTO_FEAR_GREED = "crypto_fear_greed"
    AAII = "aaii"
    PUT_CALL_RATIO = "put_call_ratio"
    COT_REPORT = "cot_report"
    INSIDER_TRADING = "insider_trading"
    SHORT_INTEREST = "short_interest"
    FINNHUB_NEWS = "finnhub_news"


@dataclass(frozen=True, slots=True)
class SentimentSignal:
    """A single sentiment reading from one source.

    Attributes:
        source: Which source produced this signal.
        score: Sentiment score in [-1, 1] (negative=fear, positive=greed).
        confidence: Reliability of this reading in [0, 1].
        timestamp: UTC timestamp when the reading was captured.
        raw_value: Original value from the source (e.g. 75 for F&G index).
    """

    source: SentimentSource
    score: float
    confidence: float
    timestamp: datetime
    raw_value: float | None = None

    def __post_init__(self) -> None:
        if not -1.0 <= self.score <= 1.0:
            raise ValueError(f"score must be in [-1, 1], got {self.score}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be in [0, 1], got {self.confidence}"
            )
