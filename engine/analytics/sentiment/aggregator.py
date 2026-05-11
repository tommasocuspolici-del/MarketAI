"""Sentiment composite — weighted aggregation of N source signals.

Rule 26: minimum 3 sources needed for a reliable composite reading. Below 3
sources, a low confidence value is reported and a warning emitted.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import yaml

from engine.analytics.sentiment.signal_model import SentimentSignal, SentimentSource
from shared.exceptions import SentimentAggregationError
from shared.logger import get_logger
from shared.types import now_utc

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

__version__ = "6.0.0"

__all__ = ["CompositeSentiment", "SentimentAggregator"]

log = get_logger(__name__)

# Default equal weights — overridable via config/sentiment_sources.yaml
_DEFAULT_WEIGHTS: Mapping[SentimentSource, float] = {
    SentimentSource.CNN_FEAR_GREED: 0.18,
    SentimentSource.CRYPTO_FEAR_GREED: 0.10,
    SentimentSource.AAII: 0.15,
    SentimentSource.PUT_CALL_RATIO: 0.15,
    SentimentSource.COT_REPORT: 0.12,
    SentimentSource.INSIDER_TRADING: 0.10,
    SentimentSource.SHORT_INTEREST: 0.10,
    SentimentSource.FINNHUB_NEWS: 0.10,
}

_MIN_SOURCES_FOR_COMPOSITE = 3   # Rule 26
_EXTREME_GREED_THRESHOLD = 0.6   # Above → contrarian sell signal
_EXTREME_FEAR_THRESHOLD = -0.6   # Below → contrarian buy signal


@dataclass(frozen=True, slots=True)
class CompositeSentiment:
    """Aggregated sentiment across multiple sources.

    Attributes:
        score: Weighted composite score in [-1, 1].
        confidence: Combined confidence from contributing sources [0, 1].
        n_sources: How many sources contributed (after filtering low-conf).
        contrarian_signal: One of "extreme_greed" / "extreme_fear" / None.
        timestamp: When this composite was computed.
        per_source_scores: Mapping {source: score} for transparency.
    """

    score: float
    confidence: float
    n_sources: int
    contrarian_signal: str | None
    timestamp: datetime
    per_source_scores: dict[str, float]

    @property
    def is_extreme(self) -> bool:
        """True if a contrarian signal is active."""
        return self.contrarian_signal is not None


class SentimentAggregator:
    """Weighted aggregator for multi-source sentiment.

    Loads weights from `config/sentiment_sources.yaml` (key
    'composite_weights'), falling back to equal-ish defaults if missing.
    """

    def __init__(self, weights_path: Path | None = None) -> None:
        self._weights = self._load_weights(weights_path)
        # Normalize to sum=1 (defensive)
        total = sum(self._weights.values())
        if total <= 0:
            raise SentimentAggregationError("weights sum to zero")
        self._weights = {k: v / total for k, v in self._weights.items()}

    @staticmethod
    def _load_weights(
        path: Path | None,
    ) -> dict[SentimentSource, float]:
        weights = dict(_DEFAULT_WEIGHTS)
        cfg_path = path or Path("config/sentiment_sources.yaml")
        if cfg_path.exists():
            data = yaml.safe_load(cfg_path.read_text()) or {}
            cw = data.get("composite_weights", {})
            for src_name, w in cw.items():
                try:
                    src = SentimentSource(src_name)
                    weights[src] = float(w)
                except ValueError:
                    log.warning("sentiment.unknown_source", source=src_name)
        return weights

    def aggregate(
        self, signals: list[SentimentSignal]
    ) -> CompositeSentiment:
        """Compute a weighted composite from a list of source signals.

        Args:
            signals: Heterogeneous list (can include duplicates per source —
                the most recent wins).

        Returns:
            CompositeSentiment with score, confidence, and contrarian flag.

        Raises:
            SentimentAggregationError: if no signals provided.
        """
        if not signals:
            raise SentimentAggregationError("no signals provided")

        # Keep only the most recent signal per source (Rule 14: cleaning)
        latest: dict[SentimentSource, SentimentSignal] = {}
        for s in signals:
            cur = latest.get(s.source)
            if cur is None or s.timestamp > cur.timestamp:
                latest[s.source] = s

        # Deduplicated list, sorted for determinism
        sigs = sorted(latest.values(), key=lambda x: x.source.value)
        n_sources = len(sigs)

        # Weighted sum — only across sources we actually have
        scores = np.array([s.score for s in sigs], dtype=np.float64)
        confs = np.array([s.confidence for s in sigs], dtype=np.float64)
        weights = np.array(
            [self._weights.get(s.source, 0.0) for s in sigs], dtype=np.float64
        )

        # Renormalize weights over present sources
        weights_sum = weights.sum()
        if weights_sum <= 0:
            raise SentimentAggregationError(
                "all sources have zero weight"
            )
        weights = weights / weights_sum

        # Confidence-weighted score for robustness
        effective_weights = weights * confs
        eff_sum = effective_weights.sum()
        if eff_sum <= 0:
            raise SentimentAggregationError(
                "effective confidence-weight is zero"
            )
        composite_score = float((scores * effective_weights).sum() / eff_sum)
        composite_conf = float((confs * weights).sum())

        # Rule 26: confidence penalty if < 3 sources
        if n_sources < _MIN_SOURCES_FOR_COMPOSITE:
            log.warning(
                "sentiment.insufficient_sources",
                n=n_sources,
                threshold=_MIN_SOURCES_FOR_COMPOSITE,
            )
            composite_conf *= 0.5

        # Contrarian detection
        contrarian: str | None = None
        if composite_score >= _EXTREME_GREED_THRESHOLD:
            contrarian = "extreme_greed"
        elif composite_score <= _EXTREME_FEAR_THRESHOLD:
            contrarian = "extreme_fear"

        return CompositeSentiment(
            score=composite_score,
            confidence=composite_conf,
            n_sources=n_sources,
            contrarian_signal=contrarian,
            timestamp=now_utc(),
            per_source_scores={s.source.value: s.score for s in sigs},
        )
