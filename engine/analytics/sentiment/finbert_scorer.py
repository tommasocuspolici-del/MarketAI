"""FinBERTScorer — financial sentiment scoring with FinBERT or VADER fallback.

When feature_flag "sentiment_finbert" is True AND transformers+torch are
installed: uses ProsusAI/finbert (fine-tuned on 10k financial phrases).
Otherwise: falls back to VADER (also valid, just less accurate).

Accuracy vs VADER: FinBERT +25-30% on financial text (FPB benchmark).
Latency: ~3s per batch of 32 on CPU. Acceptable given 30-min refresh cycle.

Feature flag override: set sentiment_finbert: false in config/feature_flags.yaml
if RAM < 4 GB or CPU is very slow.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shared.feature_flags import is_enabled
from shared.logger import get_logger
from shared.resilience.error_policy import apply_error_policy

__version__ = "10.0.0"

__all__ = [
    "FinBERTScorer",
    "SentimentLabel",
]

log = get_logger(__name__)

_FINBERT_MODEL = "ProsusAI/finbert"
_BATCH_SIZE    = 32
_MAX_LENGTH    = 512


@dataclass(frozen=True)
class SentimentLabel:
    label:      str     # "positive" | "negative" | "neutral"
    score:      float   # [-1, 1]  (positive=+, negative=−, neutral≈0)
    confidence: float   # [0, 1] softmax probability
    model:      str     # "finbert" | "vader"


class FinBERTScorer:
    """Financial sentiment scorer with automatic FinBERT ↔ VADER selection.

    Usage::

        scorer = FinBERTScorer()
        label  = scorer.score_text("Fed raises rates by 50bps")
        batch  = scorer.score_batch(["Earnings beat", "Revenue miss"])
    """

    def __init__(self) -> None:
        self._pipeline: Any = None
        self._vader: Any    = None
        self._model_name = "vader"

        if is_enabled("sentiment_finbert"):
            self._pipeline = self._try_load_finbert()

        if self._pipeline is None:
            self._vader    = self._load_vader()
            self._model_name = "vader"
        else:
            self._model_name = "finbert"

    # ── Public API ─────────────────────────────────────────────────────────

    def score_text(self, text: str) -> SentimentLabel:
        """Score a single text string."""
        results = self.score_batch([text])
        return results[0]

    def score_batch(self, texts: list[str]) -> list[SentimentLabel]:
        """Score a batch of texts. Returns one SentimentLabel per input."""
        if not texts:
            return []
        if self._pipeline is not None:
            return self._score_with_finbert(texts)
        return self._score_with_vader(texts)

    @property
    def model_name(self) -> str:
        return self._model_name

    # ── FinBERT path ───────────────────────────────────────────────────────

    @staticmethod
    def _try_load_finbert() -> Any:
        try:
            from transformers import pipeline  # noqa: PLC0415
            pipe = pipeline(
                "text-classification",
                model   = _FINBERT_MODEL,
                top_k   = None,
                truncation = True,
                max_length = _MAX_LENGTH,
            )
            log.info("finbert_scorer.loaded", model=_FINBERT_MODEL)
            return pipe
        except Exception as exc:
            log.warning(
                "finbert_scorer.load_failed",
                error=str(exc),
                fallback="vader",
            )
            return None

    def _score_with_finbert(self, texts: list[str]) -> list[SentimentLabel]:
        results: list[SentimentLabel] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            try:
                raw = self._pipeline(batch)
                for item in raw:
                    label, confidence = self._parse_finbert_output(item)
                    results.append(SentimentLabel(
                        label      = label,
                        score      = self._label_to_score(label, confidence),
                        confidence = confidence,
                        model      = "finbert",
                    ))
            except Exception as exc:
                log.error("finbert_scorer.batch_failed", error=str(exc))
                results.extend(self._score_with_vader(batch))
        return results

    @staticmethod
    def _parse_finbert_output(item: Any) -> tuple[str, float]:
        if isinstance(item, list):
            best = max(item, key=lambda x: x["score"])
        else:
            best = item
        return best["label"].lower(), float(best["score"])

    @staticmethod
    def _label_to_score(label: str, confidence: float) -> float:
        if label == "positive":
            return float(confidence)
        if label == "negative":
            return float(-confidence)
        return 0.0

    # ── VADER path ─────────────────────────────────────────────────────────

    @staticmethod
    def _load_vader() -> Any:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer  # noqa: PLC0415
        return SentimentIntensityAnalyzer()

    def _score_with_vader(self, texts: list[str]) -> list[SentimentLabel]:
        results: list[SentimentLabel] = []
        for text in texts:
            scores = self._vader.polarity_scores(text)
            compound = float(scores["compound"])    # [-1, 1]
            if compound >= 0.05:
                label = "positive"
            elif compound <= -0.05:
                label = "negative"
            else:
                label = "neutral"
            confidence = float(abs(compound))
            results.append(SentimentLabel(
                label      = label,
                score      = compound,
                confidence = confidence,
                model      = "vader",
            ))
        return results
