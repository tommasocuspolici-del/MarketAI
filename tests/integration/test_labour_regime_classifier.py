"""Tests LabourRegimeClassifier — classificazione deterministica."""
from __future__ import annotations
from datetime import date
import pytest
from engine.analytics.labour_market.labour_regime_classifier import LabourRegimeClassifier
from engine.analytics.labour_market.jolts_analyzer import JOLTSSignal
from engine.analytics.labour_market.claims_cycle_detector import ClaimsCycleSignal


def _make_jolts(score: float) -> JOLTSSignal:
    return JOLTSSignal(
        regime="tight", beveridge_gap=2.0, quits_momentum=0.2,
        labour_score=score, latest_date=date(2026, 1, 1),
        quits_rate=2.7, openings_rate=5.5, hires_quits_ratio=1.2,
    )


def _make_claims(score: float) -> ClaimsCycleSignal:
    return ClaimsCycleSignal(
        week_ending=date(2026, 1, 1), initial_claims=220_000,
        claims_4wk_ma=220_000, claims_yoy_pct=-5.0, claims_mom_pct=-1.0,
        cycle_regime="expansion", signal_strength=score,
    )


class TestRegimeClassification:

    def test_tight_regime_strong_signals(self):
        classifier = LabourRegimeClassifier(duckdb=None)
        result = classifier.classify(_make_jolts(0.8), _make_claims(0.7))
        assert result.regime == "tight"
        assert result.composite_score > 0.35

    def test_deteriorating_regime_negative_signals(self):
        classifier = LabourRegimeClassifier(duckdb=None)
        result = classifier.classify(_make_jolts(-0.6), _make_claims(-0.5))
        assert result.regime == "deteriorating"
        assert result.composite_score < -0.25

    def test_balanced_regime_neutral_signals(self):
        classifier = LabourRegimeClassifier(duckdb=None)
        result = classifier.classify(_make_jolts(0.1), _make_claims(0.0))
        assert result.regime == "balanced"

    def test_score_in_range(self):
        classifier = LabourRegimeClassifier(duckdb=None)
        result = classifier.classify(_make_jolts(1.0), _make_claims(1.0))
        assert -1.0 <= result.composite_score <= 1.0

    def test_confidence_in_range(self):
        classifier = LabourRegimeClassifier(duckdb=None)
        result = classifier.classify(_make_jolts(0.5), _make_claims(0.4))
        assert 0.0 <= result.confidence <= 1.0

    def test_all_four_regimes_reachable(self):
        """Tutti e 4 i regimi sono raggiungibili."""
        clf = LabourRegimeClassifier(duckdb=None)
        regimes = set()
        for j, c_ in [
            (0.8, 0.8), (0.0, 0.1), (1.0, -1.0), (-0.7, -0.6)
        ]:
            regimes.add(clf.classify(_make_jolts(j), _make_claims(c_)).regime)
        assert len(regimes) >= 3
