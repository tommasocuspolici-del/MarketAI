"""Tests for engine.analytics.pipeline + engine.alerts."""
from __future__ import annotations

import time
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from engine.alerts import (
    Alert,
    AlertRule,
    AlertSeverity,
    AlertType,
    RuleEngine,
)
from engine.analytics.pipeline import (
    AnalysisPipeline,
    PipelineReport,
    RiskScore,
)
from engine.analytics.sentiment import (
    SentimentSignal,
    SentimentSource,
)
from shared.exceptions import PipelineError


def _make_prices(n_tickers: int = 5, n_obs: int = 252, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_obs, freq="D", tz="UTC")
    return pd.DataFrame({
        f"TICK{i}": 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.018, n_obs)))
        for i in range(n_tickers)
    }, index=dates)


def _make_signals(n: int = 3) -> list[SentimentSignal]:
    now = datetime.now(UTC)
    sources = list(SentimentSource)[:n]
    return [
        SentimentSignal(src, score=0.2, confidence=0.85, timestamp=now)
        for src in sources
    ]


# ═══════════════════════════════════════════════════════════════════════════
# AnalysisPipeline
# ═══════════════════════════════════════════════════════════════════════════
class TestAnalysisPipeline:
    def test_basic_run(self) -> None:
        pipeline = AnalysisPipeline()
        report = pipeline.run(_make_prices(5, 252))
        assert isinstance(report, PipelineReport)
        assert report.n_tickers == 5
        assert report.duration_ms > 0
        assert report.sentiment is None  # No signals provided

    def test_with_sentiment(self) -> None:
        pipeline = AnalysisPipeline()
        report = pipeline.run(_make_prices(5, 252), _make_signals(3))
        assert report.sentiment is not None
        assert report.sentiment.n_sources == 3

    def test_empty_prices_raises(self) -> None:
        pipeline = AnalysisPipeline()
        with pytest.raises(PipelineError, match="empty"):
            pipeline.run(pd.DataFrame())

    def test_single_ticker_raises(self) -> None:
        pipeline = AnalysisPipeline()
        with pytest.raises(PipelineError, match="at least 2"):
            pipeline.run(_make_prices(n_tickers=1))

    def test_risk_score_in_range(self) -> None:
        pipeline = AnalysisPipeline()
        report = pipeline.run(_make_prices(5, 252))
        assert isinstance(report.risk_score, RiskScore)
        assert 0.0 <= report.risk_score.score <= 100.0
        assert report.risk_score.label in ("low", "moderate", "elevated", "extreme")

    def test_risk_score_breakdown_keys(self) -> None:
        pipeline = AnalysisPipeline()
        report = pipeline.run(_make_prices(5, 252))
        breakdown = report.risk_score.breakdown
        assert "regime" in breakdown
        assert "volatility" in breakdown
        assert "correlation" in breakdown
        assert "sentiment" in breakdown

    def test_stage_durations_recorded(self) -> None:
        pipeline = AnalysisPipeline()
        report = pipeline.run(_make_prices(5, 252))
        assert "correlation" in report.stage_durations
        assert "regime" in report.stage_durations
        assert "risk_score" in report.stage_durations
        assert all(v >= 0 for v in report.stage_durations.values())


# ═══════════════════════════════════════════════════════════════════════════
# Performance — DoD: pipeline < 10s on 10 tickers
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.benchmark
class TestPipelinePerformance:
    def test_10_tickers_under_10s(self) -> None:
        """DoD Phase 8: pipeline end-to-end < 10s on 10 tickers."""
        pipeline = AnalysisPipeline()
        prices = _make_prices(n_tickers=10, n_obs=252)
        sigs = _make_signals(8)
        t0 = time.monotonic()
        report = pipeline.run(prices, sigs)
        elapsed = time.monotonic() - t0
        assert report.n_tickers == 10
        assert elapsed < 10.0, f"expected <10s, got {elapsed:.2f}s"


# ═══════════════════════════════════════════════════════════════════════════
# Alerts — RuleEngine
# ═══════════════════════════════════════════════════════════════════════════
class TestRuleEngine:
    def test_loads_rules_from_yaml(self) -> None:
        engine = RuleEngine()
        # config/alert_rules.yaml has 6 rules
        assert len(engine.rules) >= 4

    def test_inline_rule(self) -> None:
        rule = AlertRule(
            rule_id="test_rule",
            type=AlertType.RISK_SCORE_HIGH,
            severity=AlertSeverity.WARNING,
            field_path="risk_score.score",
            op="ge",
            value=50.0,
            message_template="Risk: {value}",
        )
        engine = RuleEngine(rules=[rule])
        # Build a context that triggers the rule
        ctx = {"risk_score": type("RS", (), {"score": 75.0})()}
        alerts = engine.evaluate(ctx)
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.WARNING

    def test_no_match_returns_empty(self) -> None:
        rule = AlertRule(
            rule_id="rs",
            type=AlertType.RISK_SCORE_HIGH,
            severity=AlertSeverity.WARNING,
            field_path="risk_score.score",
            op="ge",
            value=99.0,
            message_template="X",
        )
        engine = RuleEngine(rules=[rule])
        ctx = {"risk_score": type("RS", (), {"score": 25.0})()}
        alerts = engine.evaluate(ctx)
        assert alerts == []

    def test_dedup_within_window(self) -> None:
        """Same alert within dedup window → emitted only once."""
        rule = AlertRule(
            rule_id="dedup_test",
            type=AlertType.RISK_SCORE_HIGH,
            severity=AlertSeverity.WARNING,
            field_path="risk_score.score",
            op="ge",
            value=50.0,
            message_template="Risk: {value}",
            dedup_window_minutes=60,
        )
        engine = RuleEngine(rules=[rule])
        ctx = {"risk_score": type("RS", (), {"score": 75.0})()}
        first = engine.evaluate(ctx)
        second = engine.evaluate(ctx)
        assert len(first) == 1
        assert len(second) == 0

    def test_dedup_bypass(self) -> None:
        rule = AlertRule(
            rule_id="dedup_bypass",
            type=AlertType.RISK_SCORE_HIGH,
            severity=AlertSeverity.WARNING,
            field_path="risk_score.score",
            op="ge",
            value=50.0,
            message_template="X",
        )
        engine = RuleEngine(rules=[rule])
        ctx = {"risk_score": type("RS", (), {"score": 75.0})()}
        first = engine.evaluate(ctx)
        second = engine.evaluate(ctx, suppress_dedup=True)
        assert len(first) == 1
        assert len(second) == 1


class TestAlertOps:
    @pytest.mark.parametrize("op,actual,expected,result", [
        ("eq",  "bull", "bull", True),
        ("eq",  "bear", "bull", False),
        ("ne",  "bull", "bear", True),
        ("gt",  10.0, 5.0, True),
        ("ge",  10.0, 10.0, True),
        ("lt",  5.0, 10.0, True),
        ("le",  10.0, 10.0, True),
    ])
    def test_op_matrix(self, op: str, actual: object, expected: object, result: bool) -> None:
        rule = AlertRule(
            rule_id="op",
            type=AlertType.ANOMALY,
            severity=AlertSeverity.INFO,
            field_path="x",
            op=op,
            value=expected,  # type: ignore[arg-type]
            message_template="X",
        )
        engine = RuleEngine(rules=[rule])
        alerts = engine.evaluate({"x": actual}, suppress_dedup=True)
        assert (len(alerts) == 1) == result


# ═══════════════════════════════════════════════════════════════════════════
# End-to-end: pipeline → context → alerts
# ═══════════════════════════════════════════════════════════════════════════
class TestPipelineToAlerts:
    def test_full_workflow(self) -> None:
        """Pipeline output feeds RuleEngine and produces alerts."""
        pipeline = AnalysisPipeline()
        report = pipeline.run(_make_prices(5, 252), _make_signals(3))

        engine = RuleEngine()
        ctx = {
            "regime": report.regime,
            "risk_score": report.risk_score,
            "sentiment": report.sentiment,
        }
        alerts = engine.evaluate(ctx)
        # Always returns a (possibly empty) list of Alerts
        assert isinstance(alerts, list)
        for a in alerts:
            assert isinstance(a, Alert)
            assert a.severity in AlertSeverity
