"""Tests per DCCEWMAEnhanced — matrice correlazione con shrinkage."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.analytics.correlation.dcc_ewma_enhanced import DCCEWMAEnhanced, DCCEWMAEnhancedResult


@pytest.fixture()
def ewma():
    return DCCEWMAEnhanced(min_periods=30)


def _random_returns(n: int = 252, n_assets: int = 3, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data = rng.normal(0, 0.01, (n, n_assets))
    return pd.DataFrame(data, columns=[f"A{i}" for i in range(n_assets)])


class TestDCCEWMAEnhancedOutput:
    def test_returns_result_instance(self, ewma):
        df = _random_returns()
        result = ewma.compute(df)
        assert isinstance(result, DCCEWMAEnhancedResult)

    def test_correlation_matrix_shape(self, ewma):
        df = _random_returns(n_assets=4)
        result = ewma.compute(df)
        assert result.correlation_matrix.shape == (4, 4)

    def test_diagonal_is_one(self, ewma):
        df = _random_returns()
        result = ewma.compute(df)
        diag = np.diag(result.correlation_matrix)
        np.testing.assert_allclose(diag, 1.0, atol=1e-9)

    def test_correlation_in_valid_range(self, ewma):
        df = _random_returns()
        result = ewma.compute(df)
        assert np.all(result.correlation_matrix >= -1.0 - 1e-8)
        assert np.all(result.correlation_matrix <= 1.0 + 1e-8)

    def test_matrix_is_psd(self, ewma):
        df = _random_returns(n_assets=5)
        result = ewma.compute(df)
        assert result.is_psd

    def test_insufficient_data_returns_identity(self, ewma):
        df = _random_returns(n=10)
        result = ewma.compute(df)
        np.testing.assert_array_equal(result.correlation_matrix, np.eye(3))

    def test_asset_names_match(self, ewma):
        df = _random_returns(n_assets=3)
        result = ewma.compute(df)
        assert result.asset_names == list(df.columns)

    def test_regime_conditioning(self, ewma):
        df = _random_returns(n=252)
        labels = pd.Series(
            ["bull"] * 126 + ["bear"] * 126,
            index=df.index,
        )
        result = ewma.compute(df, regime_labels=labels)
        assert isinstance(result, DCCEWMAEnhancedResult)


class TestEWMACorrelationMath:
    def test_perfect_correlation(self):
        x = np.linspace(0, 1, 100)
        df = pd.DataFrame({"A": x, "B": x})
        ewma = DCCEWMAEnhanced(min_periods=10)
        result = ewma.compute(df)
        # Perfetta correlazione → matrice [[1,1],[1,1]]
        assert result.correlation_matrix[0, 1] > 0.9

    def test_perfect_anticorrelation(self):
        x = np.linspace(0, 1, 100)
        df = pd.DataFrame({"A": x, "B": -x})
        ewma = DCCEWMAEnhanced(min_periods=10)
        result = ewma.compute(df)
        assert result.correlation_matrix[0, 1] < -0.9

    def test_optimal_lambda_in_grid_range(self):
        ewma = DCCEWMAEnhanced()
        x = np.random.default_rng(0).normal(0, 0.01, 200)
        y = np.random.default_rng(1).normal(0, 0.01, 200)
        lam = ewma._find_optimal_lambda(x, y)
        assert 0.89 <= lam <= 1.0

    def test_shrinkage_applied_when_not_psd(self):
        matrix = np.array([[1.0, 0.9, 0.9],
                            [0.9, 1.0, 0.9],
                            [0.9, 0.9, 1.0]])
        result = DCCEWMAEnhanced._ledoit_wolf_shrinkage(matrix)
        eigvals = np.linalg.eigvalsh(result)
        assert np.all(eigvals >= -1e-8)
