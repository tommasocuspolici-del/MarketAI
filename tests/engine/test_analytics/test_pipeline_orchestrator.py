"""Tests — engine.analytics.pipeline.orchestrator (Fase 4 Qualità Segnali).

Copre AnalysisPipeline, PipelineReport, RiskScore con dati sintetici.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from engine.analytics.pipeline.orchestrator import (
    AnalysisPipeline,
    PipelineReport,
    RiskScore,
    _classify_risk,
)
from shared.exceptions import PipelineError


# ── Fixtures ────────────────────────────────────────────────────────────────

def _prices(n: int = 62, tickers: int = 4, seed: int = 42) -> pd.DataFrame:
    """Synthetic daily OHLCV close prices, UTC-aware DatetimeIndex."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(
        datetime(2025, 1, 1, tzinfo=UTC), periods=n, freq="D"
    )
    cols = [f"T{i}" for i in range(tickers)]
    data = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, (n, tickers)), axis=0)
    return pd.DataFrame(data, index=idx, columns=cols)


# ── RiskScore label ──────────────────────────────────────────────────────────

class TestClassifyRisk:
    def test_extreme(self) -> None:
        assert _classify_risk(80.0) == "extreme"

    def test_elevated(self) -> None:
        assert _classify_risk(60.0) == "elevated"

    def test_moderate(self) -> None:
        assert _classify_risk(30.0) == "moderate"

    def test_low(self) -> None:
        assert _classify_risk(10.0) == "low"

    def test_boundary_75_extreme(self) -> None:
        assert _classify_risk(75.0) == "extreme"

    def test_boundary_50_elevated(self) -> None:
        assert _classify_risk(50.0) == "elevated"

    def test_boundary_25_moderate(self) -> None:
        assert _classify_risk(25.0) == "moderate"


# ── AnalysisPipeline ─────────────────────────────────────────────────────────

class TestAnalysisPipelineValidation:
    def test_empty_prices_raises(self) -> None:
        pipe = AnalysisPipeline()
        with pytest.raises(PipelineError, match="empty"):
            pipe.run(pd.DataFrame())

    def test_single_ticker_raises(self) -> None:
        pipe = AnalysisPipeline()
        idx = pd.date_range(datetime(2025, 1, 1, tzinfo=UTC), periods=30, freq="D")
        with pytest.raises(PipelineError, match="2 tickers"):
            pipe.run(pd.DataFrame({"A": np.ones(30)}, index=idx))


class TestAnalysisPipelineRun:
    def test_returns_pipeline_report(self) -> None:
        pipe = AnalysisPipeline()
        report = pipe.run(_prices())
        assert isinstance(report, PipelineReport)

    def test_duration_positive(self) -> None:
        pipe = AnalysisPipeline()
        report = pipe.run(_prices())
        assert report.duration_ms > 0

    def test_started_before_completed(self) -> None:
        pipe = AnalysisPipeline()
        report = pipe.run(_prices())
        assert report.started_at <= report.completed_at

    def test_risk_score_bounded(self) -> None:
        pipe = AnalysisPipeline()
        report = pipe.run(_prices())
        assert 0.0 <= report.risk_score.score <= 100.0

    def test_risk_score_has_label(self) -> None:
        pipe = AnalysisPipeline()
        report = pipe.run(_prices())
        assert report.risk_score.label in ("low", "moderate", "elevated", "extreme")

    def test_risk_score_breakdown_non_empty(self) -> None:
        pipe = AnalysisPipeline()
        report = pipe.run(_prices())
        assert len(report.risk_score.breakdown) > 0

    def test_n_tickers_correct(self) -> None:
        pipe = AnalysisPipeline()
        prices = _prices(tickers=5)
        report = pipe.run(prices)
        assert report.n_tickers == 5

    def test_stage_durations_populated(self) -> None:
        pipe = AnalysisPipeline()
        report = pipe.run(_prices())
        assert "correlation" in report.stage_durations
        assert all(v >= 0 for v in report.stage_durations.values())

    def test_correlation_report_present(self) -> None:
        pipe = AnalysisPipeline()
        report = pipe.run(_prices())
        assert report.correlation is not None

    def test_regime_report_present(self) -> None:
        pipe = AnalysisPipeline()
        report = pipe.run(_prices())
        assert report.regime is not None

    def test_sentiment_none_when_no_signals(self) -> None:
        pipe = AnalysisPipeline()
        report = pipe.run(_prices(), sentiment_signals=None)
        assert report.sentiment is None

    def test_with_sentiment_signals(self) -> None:
        from engine.analytics.sentiment import SentimentSignal, SentimentSource
        pipe = AnalysisPipeline()
        sigs = [
            SentimentSignal(
                source=SentimentSource.CNN_FEAR_GREED,
                score=0.4,
                confidence=0.8,
                timestamp=datetime.now(UTC),
            ),
            SentimentSignal(
                source=SentimentSource.AAII,
                score=0.2,
                confidence=0.85,
                timestamp=datetime.now(UTC),
            ),
            SentimentSignal(
                source=SentimentSource.PUT_CALL_RATIO,
                score=0.3,
                confidence=0.9,
                timestamp=datetime.now(UTC),
            ),
        ]
        report = pipe.run(_prices(), sentiment_signals=sigs)
        assert report.sentiment is not None

    def test_pipeline_performance_under_500ms(self) -> None:
        import time
        pipe = AnalysisPipeline()
        prices = _prices(n=252, tickers=6)
        t0 = time.monotonic()
        pipe.run(prices)
        elapsed_ms = (time.monotonic() - t0) * 1000
        assert elapsed_ms < 500, f"Pipeline lenta: {elapsed_ms:.0f}ms > 500ms"

    def test_deterministic_on_same_input(self) -> None:
        pipe = AnalysisPipeline()
        prices = _prices(seed=99)
        r1 = pipe.run(prices)
        r2 = pipe.run(prices)
        assert abs(r1.risk_score.score - r2.risk_score.score) < 0.01


class TestAnalysisPipelineWeights:
    def test_weights_sum_near_one(self) -> None:
        w = (
            AnalysisPipeline._W_REGIME
            + AnalysisPipeline._W_VOL
            + AnalysisPipeline._W_CORRELATION
            + AnalysisPipeline._W_SENTIMENT
        )
        assert abs(w - 1.0) < 1e-9

    def test_all_weights_positive(self) -> None:
        assert AnalysisPipeline._W_REGIME > 0
        assert AnalysisPipeline._W_VOL > 0
        assert AnalysisPipeline._W_CORRELATION > 0
        assert AnalysisPipeline._W_SENTIMENT > 0
