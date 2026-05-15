"""Tests per CrossAssetMatrix — 13 asset, diversification score, signal."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.analytics.correlation.cross_asset_matrix import (
    CrossAssetMatrix,
    CrossAssetMatrixResult,
    _DEFAULT_UNIVERSE,
)


@pytest.fixture()
def matrix():
    return CrossAssetMatrix(client=None)


def _make_returns(tickers: list[str], n: int = 252, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data = rng.normal(0, 0.01, (n, len(tickers)))
    return pd.DataFrame(data, columns=tickers)


class TestCrossAssetMatrixOutput:
    def test_compute_returns_result(self, matrix):
        df = _make_returns(list(_DEFAULT_UNIVERSE.keys())[:5])
        result = matrix.compute(df)
        assert isinstance(result, CrossAssetMatrixResult)

    def test_insufficient_assets_returns_empty(self, matrix):
        df = _make_returns(["SPY", "TLT"])
        result = matrix.compute(df)
        assert result.diversification_score == 1.0
        assert result.correlation_signal == 0.0

    def test_diversification_score_in_range(self, matrix):
        df = _make_returns(["SPY", "TLT", "GLD", "HYG", "^VIX"])
        result = matrix.compute(df)
        assert 0.0 <= result.diversification_score <= 1.0

    def test_correlation_signal_in_range(self, matrix):
        df = _make_returns(["SPY", "TLT", "GLD", "HYG", "^VIX"])
        result = matrix.compute(df)
        assert -1.0 <= result.correlation_signal <= 1.0

    def test_vix_regime_is_valid(self, matrix):
        df = _make_returns(["SPY", "TLT", "GLD", "^VIX"])
        result = matrix.compute(df)
        assert result.vix_regime in ("crisis_coupling", "normal", "divergence")

    def test_asset_names_subset_of_universe(self, matrix):
        tickers = ["SPY", "TLT", "GLD", "NONEXISTENT_XYZ"]
        df = _make_returns(tickers)
        result = matrix.compute(df)
        for name in result.asset_names:
            assert name in _DEFAULT_UNIVERSE

    def test_correlation_matrix_shape(self, matrix):
        tickers = ["SPY", "TLT", "GLD", "HYG"]
        df = _make_returns(tickers)
        result = matrix.compute(df)
        n = len(result.asset_names)
        assert result.correlation_matrix.shape == (n, n)

    def test_full_universe(self, matrix):
        df = _make_returns(list(_DEFAULT_UNIVERSE.keys()))
        result = matrix.compute(df)
        assert len(result.asset_names) > 0
        assert result.diversification_score > 0.0


class TestDiversificationScore:
    def test_uncorrelated_gives_high_score(self):
        n = 5
        matrix = np.eye(n)
        score = CrossAssetMatrix._diversification_score(matrix)
        assert score == pytest.approx(1.0)

    def test_fully_correlated_gives_low_score(self):
        n = 4
        matrix = np.ones((n, n))
        np.fill_diagonal(matrix, 1.0)
        score = CrossAssetMatrix._diversification_score(matrix)
        assert score < 0.1

    def test_single_asset_returns_one(self):
        score = CrossAssetMatrix._diversification_score(np.array([[1.0]]))
        assert score == 1.0


class TestSignalComputation:
    def test_high_diversification_positive_signal(self):
        matrix = np.eye(5)
        names = ["SPY", "TLT", "GLD", "HYG", "USO"]
        signal = CrossAssetMatrix._compute_signal(0.9, matrix, names)
        assert signal > 0.0

    def test_low_diversification_negative_signal(self):
        n = 5
        matrix = np.ones((n, n))
        np.fill_diagonal(matrix, 1.0)
        names = ["SPY", "TLT", "GLD", "HYG", "USO"]
        signal = CrossAssetMatrix._compute_signal(0.05, matrix, names)
        assert signal < 0.0

    def test_signal_clipped_to_minus_one_plus_one(self):
        signal = CrossAssetMatrix._compute_signal(0.5, np.eye(3), ["A", "B", "C"])
        assert -1.0 <= signal <= 1.0
