"""Analysis pipeline — end-to-end orchestrator (Rule 12).

Combines: market data fetching → cleaning → quality validation →
correlation analysis → regime detection → sentiment composite →
composite risk score → alerts.

This is the CRITICAL workflow run by the scheduler every 4h on business days.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from engine.analytics.correlation import (
    CorrelationAnalyzer,
    CorrelationReport,
    RegimeDetector,
    RegimeReport,
)
from engine.analytics.sentiment import (
    CompositeSentiment,
    SentimentAggregator,
    SentimentSignal,
)
from shared.exceptions import PipelineError
from shared.logger import get_logger
from shared.types import now_utc

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    import pandas as pd

__version__ = "6.0.0"

__all__ = ["AnalysisPipeline", "PipelineReport", "RiskScore"]

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RiskScore:
    """Composite risk score in [0, 100]; higher = more risk."""

    score: float
    breakdown: dict[str, float]    # contributions per factor
    label: str                     # "low" | "moderate" | "elevated" | "extreme"


@dataclass(frozen=True, slots=True)
class PipelineReport:
    """Full output of one pipeline run."""

    started_at: datetime
    completed_at: datetime
    duration_ms: float
    correlation: CorrelationReport
    regime: RegimeReport
    sentiment: CompositeSentiment | None
    risk_score: RiskScore
    n_tickers: int
    stage_durations: dict[str, float] = field(default_factory=dict)


def _classify_risk(score: float) -> str:
    if score >= 75:
        return "extreme"
    if score >= 50:
        return "elevated"
    if score >= 25:
        return "moderate"
    return "low"


class AnalysisPipeline:
    """End-to-end analysis orchestrator.

    Pipeline stages:
        1. Validate inputs
        2. Correlation analysis (CorrelationAnalyzer)
        3. Regime detection on aggregate / first ticker (RegimeDetector)
        4. Sentiment composite (SentimentAggregator) — optional
        5. Composite risk score
        6. Build PipelineReport
    """

    # Risk score weights — must sum to ~1.0
    _W_REGIME = 0.40
    _W_VOL = 0.30
    _W_CORRELATION = 0.20
    _W_SENTIMENT = 0.10

    def __init__(
        self,
        correlation_analyzer: CorrelationAnalyzer | None = None,
        regime_detector: RegimeDetector | None = None,
        sentiment_aggregator: SentimentAggregator | None = None,
    ) -> None:
        self._corr = correlation_analyzer or CorrelationAnalyzer()
        self._regime = regime_detector or RegimeDetector(n_regimes=4)
        self._sentiment = sentiment_aggregator or SentimentAggregator()

    def run(
        self,
        prices: pd.DataFrame,
        sentiment_signals: Sequence[SentimentSignal] | None = None,
    ) -> PipelineReport:
        """Run the full pipeline.

        Args:
            prices: DataFrame with shape (T, N). Must be tz-aware UTC index.
            sentiment_signals: Optional list of sentiment signals to aggregate.

        Returns:
            PipelineReport with all stage outputs + risk score.

        Raises:
            PipelineError: on validation failure or stage error.
        """
        if prices.empty:
            raise PipelineError("empty prices DataFrame")
        if prices.shape[1] < 2:
            raise PipelineError("need at least 2 tickers")

        started = now_utc()
        t0 = time.monotonic()
        durations: dict[str, float] = {}

        # Stage 1: Correlation
        s1 = time.monotonic()
        try:
            corr_report = self._corr.run(prices)
        except Exception as e:
            raise PipelineError(f"correlation stage failed: {e}") from e
        durations["correlation"] = (time.monotonic() - s1) * 1000

        # Stage 2: Regime detection on first ticker (or composite series)
        s2 = time.monotonic()
        try:
            # Use equal-weighted portfolio as the regime signal
            portfolio = prices.mean(axis=1)
            regime_report = self._regime.run(portfolio)
        except Exception as e:
            raise PipelineError(f"regime stage failed: {e}") from e
        durations["regime"] = (time.monotonic() - s2) * 1000

        # Stage 3: Sentiment (optional)
        s3 = time.monotonic()
        sentiment_composite: CompositeSentiment | None = None
        if sentiment_signals:
            try:
                sentiment_composite = self._sentiment.aggregate(
                    list(sentiment_signals)
                )
            except Exception as e:
                # Sentiment is non-critical: log and continue
                log.warning("pipeline.sentiment_failed", error=str(e))
        durations["sentiment"] = (time.monotonic() - s3) * 1000

        # Stage 4: Composite risk score
        s4 = time.monotonic()
        risk = self._compute_risk_score(
            corr_report=corr_report,
            regime_report=regime_report,
            sentiment=sentiment_composite,
        )
        durations["risk_score"] = (time.monotonic() - s4) * 1000

        completed = now_utc()
        total_ms = (time.monotonic() - t0) * 1000

        log.info(
            "pipeline.completed",
            duration_ms=total_ms,
            n_tickers=prices.shape[1],
            risk_label=risk.label,
            regime=regime_report.current_regime.label,
        )

        return PipelineReport(
            started_at=started,
            completed_at=completed,
            duration_ms=total_ms,
            correlation=corr_report,
            regime=regime_report,
            sentiment=sentiment_composite,
            risk_score=risk,
            n_tickers=prices.shape[1],
            stage_durations=durations,
        )

    def _compute_risk_score(
        self,
        corr_report: CorrelationReport,
        regime_report: RegimeReport,
        sentiment: CompositeSentiment | None,
    ) -> RiskScore:
        """Combine multiple signals into a [0, 100] composite risk score."""
        # 1. Regime contribution (stress=100, bear=70, transition=40, bull=15)
        regime_map = {"stress": 100.0, "bear": 70.0, "transition": 40.0, "bull": 15.0}
        regime_pts = regime_map.get(regime_report.current_regime.label, 40.0)

        # 2. Volatility contribution — average regime vol normalized
        vol_current = regime_report.regime_vols.get(
            regime_report.current_regime.label, 0.02
        )
        # Map vol [0, 0.05] → [0, 100] linear
        vol_pts = min(100.0, vol_current * 2000.0)

        # 3. Correlation contribution — high avg correlation = more systemic risk
        # Take avg of off-diagonal absolute correlations
        static = corr_report.static_corr.to_numpy()
        n = static.shape[0]
        if n > 1:
            mask = ~np.eye(n, dtype=bool)
            avg_abs_corr = float(np.abs(static[mask]).mean())
        else:
            avg_abs_corr = 0.0
        corr_pts = avg_abs_corr * 100.0   # [0, 100]

        # 4. Sentiment contribution — extreme greed = more risk
        # Map sentiment [-1, 1] → [0, 100] (greed = high risk); neutral when missing
        sent_pts = (sentiment.score + 1.0) * 50.0 if sentiment is not None else 50.0

        score = float(
            self._W_REGIME * regime_pts
            + self._W_VOL * vol_pts
            + self._W_CORRELATION * corr_pts
            + self._W_SENTIMENT * sent_pts
        )
        score = float(min(100.0, max(0.0, score)))

        return RiskScore(
            score=score,
            breakdown={
                "regime": regime_pts,
                "volatility": vol_pts,
                "correlation": corr_pts,
                "sentiment": sent_pts,
            },
            label=_classify_risk(score),
        )
