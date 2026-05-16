"""SourceCredibilityTracker — dynamic per-source reliability weights.

Tracks how well each news source's sentiment correlates with subsequent
price movements (IC). Updated weekly; sources with low IC get lower weight
in the composite sentiment signal.

Default weights (from config/sentiment_v2.yaml or hardcoded fallback):
  reuters:    0.90  — institutional, low noise
  bloomberg:  0.88  — institutional, low noise
  finnhub:    0.72  — aggregator, moderate
  seekingalpha: 0.65 — opinion-heavy, higher noise
  reddit:     0.40  — high noise, contrarian value
  twitter:    0.35  — very noisy
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime

from shared.constants import CONFIG_DIR
from shared.logger import get_logger

import yaml

__version__ = "10.0.0"

__all__ = ["SourceCredibilityTracker"]

log = get_logger(__name__)

_CONFIG_PATH = CONFIG_DIR / "sentiment_v2.yaml"

_DEFAULT_WEIGHTS: dict[str, float] = {
    "reuters":      0.90,
    "bloomberg":    0.88,
    "wsj":          0.85,
    "ft":           0.82,
    "cnbc":         0.75,
    "finnhub":      0.72,
    "marketwatch":  0.68,
    "seekingalpha": 0.65,
    "reddit":       0.40,
    "twitter":      0.35,
    "unknown":      0.50,    # default for unrecognised sources
}


@dataclass
class CredibilityRecord:
    source:         str
    weight:         float
    accuracy_score: float
    sample_size:    int
    last_updated:   datetime


class SourceCredibilityTracker:
    """Dynamic credibility weights for news sources.

    Weights start from defaults and are updated as IC data accumulates.
    Thread-safe via RLock.
    """

    def __init__(self) -> None:
        self._weights: dict[str, float] = dict(_DEFAULT_WEIGHTS)
        self._records: dict[str, CredibilityRecord] = {}
        self._lock = threading.RLock()
        self._load_from_yaml()

    def _load_from_yaml(self) -> None:
        try:
            cfg = yaml.safe_load(_CONFIG_PATH.read_text())
            source_weights = cfg.get("source_credibility", {})
            with self._lock:
                for source, weight in source_weights.items():
                    self._weights[source.lower()] = float(weight)
        except Exception:
            pass    # Use defaults if YAML not found

    def get_weight(self, source: str) -> float:
        """Return credibility weight [0, 1] for *source*."""
        with self._lock:
            return self._weights.get(source.lower(), self._weights["unknown"])

    def update_from_ic(
        self,
        source:         str,
        ic_estimate:    float,
        sample_size:    int,
    ) -> None:
        """Update credibility weight based on new IC measurement.

        Uses exponential smoothing: new_weight = 0.7 * old + 0.3 * ic_based_weight.
        IC-based weight: clip(ic * 10, 0.2, 1.0) — IC 0.10 → weight 1.0.
        """
        ic_weight = float(min(max(ic_estimate * 10.0, 0.2), 1.0))
        with self._lock:
            old_weight = self._weights.get(source.lower(), self._weights["unknown"])
            new_weight = 0.7 * old_weight + 0.3 * ic_weight
            self._weights[source.lower()] = round(new_weight, 4)
            self._records[source.lower()] = CredibilityRecord(
                source         = source,
                weight         = new_weight,
                accuracy_score = ic_estimate,
                sample_size    = sample_size,
                last_updated   = datetime.now(UTC),
            )
        log.info(
            "source_credibility.updated",
            source=source,
            old=round(old_weight, 3),
            new=round(new_weight, 3),
            ic=round(ic_estimate, 4),
        )

    def all_weights(self) -> dict[str, float]:
        with self._lock:
            return dict(self._weights)

    def annotate_articles(self, articles: list[dict]) -> list[dict]:
        """Add 'credibility' field to each article dict (in-place, returns list)."""
        for art in articles:
            source = art.get("source", "unknown").lower()
            art["credibility"] = self.get_weight(source)
        return articles
