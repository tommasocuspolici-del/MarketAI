"""Tests per LeadLagAnalyzer — Granger causality."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.analytics.correlation.lead_lag_analyzer import LeadLagAnalyzer, LeadLagResult


@pytest.fixture()
def analyzer():
    return LeadLagAnalyzer(client=None, lags=[1, 2, 5])


def _make_returns(n: int = 252, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 0.01, n)
    y = np.roll(x, 2) + rng.normal(0, 0.003, n)  # x leads y by 2 periods
    return pd.DataFrame({"X": x, "Y": y})


class TestLeadLagResult:
    def test_test_pair_returns_result(self, analyzer):
        df = _make_returns()
        result = analyzer.test_pair(df, "X", "Y")
        assert isinstance(result, LeadLagResult)

    def test_leader_follower_set_correctly(self, analyzer):
        df = _make_returns()
        result = analyzer.test_pair(df, "X", "Y")
        assert result.leader == "X"
        assert result.follower == "Y"

    def test_pvalue_in_valid_range(self, analyzer):
        df = _make_returns()
        result = analyzer.test_pair(df, "X", "Y")
        assert 0.0 <= result.granger_pvalue <= 1.0

    def test_optimal_lag_is_positive(self, analyzer):
        df = _make_returns()
        result = analyzer.test_pair(df, "X", "Y")
        assert result.optimal_lag_days >= 0

    def test_signal_is_valid_string(self, analyzer):
        df = _make_returns()
        result = analyzer.test_pair(df, "X", "Y")
        assert result.lead_signal in ("bullish_lead", "bearish_lead", "neutral")

    def test_missing_asset_returns_null(self, analyzer):
        df = _make_returns()
        result = analyzer.test_pair(df, "X", "NONEXISTENT")
        assert result.granger_pvalue == 1.0
        assert result.is_significant is False
        assert result.lead_signal == "neutral"

    def test_insufficient_data_returns_null(self, analyzer):
        df = pd.DataFrame({"X": [0.01] * 10, "Y": [0.01] * 10})
        result = analyzer.test_pair(df, "X", "Y")
        assert result.lead_signal == "neutral"


class TestLeadLagAllPairs:
    def test_test_all_pairs_returns_list(self, analyzer):
        df = _make_returns()
        df["Z"] = np.random.default_rng(99).normal(0, 0.01, len(df))
        results = analyzer.test_all_pairs(df, pairs=[("X", "Y"), ("X", "Z")])
        assert len(results) == 2
        assert all(isinstance(r, LeadLagResult) for r in results)

    def test_all_pairs_no_crash_with_empty_series(self, analyzer):
        df = pd.DataFrame({"A": [0.0] * 100, "B": [0.0] * 100})
        results = analyzer.test_all_pairs(df)
        assert isinstance(results, list)


class TestCrossCorr:
    def test_cross_corr_at_lag_0_equals_pearson(self):
        rng = np.random.default_rng(0)
        x = rng.normal(0, 1, 100)
        y = rng.normal(0, 1, 100)
        cc = LeadLagAnalyzer._cross_corr_at_lag(x, y, 0)
        expected = float(np.corrcoef(x, y)[0, 1])
        assert abs(cc - expected) < 1e-10

    def test_cross_corr_range(self):
        x = np.random.default_rng(0).normal(0, 1, 200)
        y = np.random.default_rng(1).normal(0, 1, 200)
        for lag in [1, 5, 10]:
            cc = LeadLagAnalyzer._cross_corr_at_lag(x, y, lag)
            assert -1.0 <= cc <= 1.0

    def test_preprocess_removes_extremes(self):
        arr = np.array([0.01] * 100 + [100.0])  # outlier enorme
        result = LeadLagAnalyzer._preprocess(arr, winsorize_sigma=3.0)
        assert result[-1] < 1.0  # outlier winsorizzato
