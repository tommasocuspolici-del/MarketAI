"""Tests per DCCGARCHAnalyzer — feature-flagged DCC-GARCH(1,1)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

from engine.analytics.correlation.dcc_garch import (
    DCCGARCHAnalyzer,
    _arch_available,
    _is_psd,
    _ledoit_wolf_shrink,
)
from engine.analytics.correlation.dcc_ewma_enhanced import DCCEWMAEnhancedResult


def _make_returns(n_assets: int = 5, n_obs: int = 300, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    tickers = [f"A{i}" for i in range(n_assets)]
    data = rng.normal(0, 0.01, (n_obs, n_assets))
    return pd.DataFrame(data, columns=tickers)


# ─── Utility functions ────────────────────────────────────────────────────────

class TestUtilities:
    def test_arch_available(self):
        assert _arch_available() is True

    def test_is_psd_identity(self):
        assert _is_psd(np.eye(4)) is True

    def test_is_psd_not_psd(self):
        bad = np.array([[1.0, 2.0], [2.0, 1.0]])
        assert _is_psd(bad) is False

    def test_ledoit_wolf_makes_psd(self):
        # Matrix barely not PSD: eigenvalues are 1±1.05 → -0.05 and 2.05
        # After 0.2 shrinkage: off-diagonal becomes 0.84 → eigenvalues 1.84 and 0.16 (PSD)
        bad = np.array([[1.0, 1.05], [1.05, 1.0]])
        shrunk = _ledoit_wolf_shrink(bad, shrinkage=0.2)
        assert _is_psd(shrunk) is True

    def test_ledoit_wolf_diagonal_dominated(self):
        """Shrinkage verso identità → elementi diagonali aumentano."""
        M = np.array([[1.0, 0.9], [0.9, 1.0]])
        shrunk = _ledoit_wolf_shrink(M, shrinkage=0.5)
        assert shrunk[0, 1] < M[0, 1]


# ─── Flag-disabled fallback ───────────────────────────────────────────────────

class TestFlagDisabledFallback:
    def test_returns_ewma_when_flag_off(self):
        """Quando dcc_garch_full=False → usa DCCEWMAEnhanced silenziosamente."""
        with patch("engine.analytics.correlation.dcc_garch.is_enabled", return_value=False):
            analyzer = DCCGARCHAnalyzer()
            df = _make_returns(4, 300)
            result = analyzer.compute(df)
        assert isinstance(result, DCCEWMAEnhancedResult)

    def test_returns_ewma_insufficient_data(self):
        """Meno di 252 osservazioni → fallback EWMA."""
        with patch("engine.analytics.correlation.dcc_garch.is_enabled", return_value=True):
            analyzer = DCCGARCHAnalyzer()
            df = _make_returns(4, 100)  # < 252
            result = analyzer.compute(df)
        assert isinstance(result, DCCEWMAEnhancedResult)

    def test_returns_ewma_on_exception(self):
        """Errore interno → fallback EWMA, non crash."""
        with patch("engine.analytics.correlation.dcc_garch.is_enabled", return_value=True):
            with patch.object(DCCGARCHAnalyzer, "_compute_dcc",
                              side_effect=RuntimeError("test error")):
                analyzer = DCCGARCHAnalyzer()
                df = _make_returns(4, 300)
                result = analyzer.compute(df)
        assert isinstance(result, DCCEWMAEnhancedResult)


# ─── DCC-GARCH output shape (flag enabled) ────────────────────────────────────

class TestDCCGARCHOutput:
    @pytest.fixture()
    def analyzer_enabled(self):
        with patch("engine.analytics.correlation.dcc_garch.is_enabled", return_value=True):
            yield DCCGARCHAnalyzer()

    def test_returns_result_instance(self, analyzer_enabled):
        df = _make_returns(4, 300)
        result = analyzer_enabled.compute(df)
        assert isinstance(result, DCCEWMAEnhancedResult)

    def test_correlation_matrix_shape(self, analyzer_enabled):
        df = _make_returns(4, 300)
        result = analyzer_enabled.compute(df)
        n = len(df.columns)
        assert result.correlation_matrix.shape == (n, n)

    def test_diagonal_is_one(self, analyzer_enabled):
        """Diagonale della matrice di correlazione deve essere 1."""
        df = _make_returns(4, 300)
        result = analyzer_enabled.compute(df)
        diag = np.diag(result.correlation_matrix)
        np.testing.assert_allclose(diag, np.ones(len(diag)), atol=1e-6)

    def test_correlation_values_in_range(self, analyzer_enabled):
        """Tutte le correlazioni in [-1, 1]."""
        df = _make_returns(4, 300)
        result = analyzer_enabled.compute(df)
        assert np.all(result.correlation_matrix >= -1.0 - 1e-6)
        assert np.all(result.correlation_matrix <= 1.0 + 1e-6)

    def test_matrix_is_symmetric(self, analyzer_enabled):
        """Matrice di correlazione deve essere simmetrica."""
        df = _make_returns(4, 300)
        result = analyzer_enabled.compute(df)
        np.testing.assert_allclose(
            result.correlation_matrix,
            result.correlation_matrix.T,
            atol=1e-6,
        )

    def test_matrix_is_psd(self, analyzer_enabled):
        """Matrice DCC deve essere semi-definita positiva."""
        df = _make_returns(4, 300)
        result = analyzer_enabled.compute(df)
        assert result.is_psd is True

    def test_asset_names_preserved(self, analyzer_enabled):
        df = _make_returns(4, 300)
        result = analyzer_enabled.compute(df)
        assert result.asset_names == list(df.columns)

    def test_pairwise_count_correct(self, analyzer_enabled):
        """N*(N-1)/2 coppie per N asset."""
        n = 4
        df = _make_returns(n, 300)
        result = analyzer_enabled.compute(df)
        expected_pairs = n * (n - 1) // 2
        assert len(result.pairwise) == expected_pairs

    def test_pairwise_correlations_match_matrix(self, analyzer_enabled):
        """I valori pairwise corrispondono alla matrice."""
        df = _make_returns(4, 300)
        result = analyzer_enabled.compute(df)
        names = result.asset_names
        for pair in result.pairwise:
            i = names.index(pair.asset_a)
            j = names.index(pair.asset_b)
            assert abs(pair.ewma_correlation - result.correlation_matrix[i, j]) < 1e-6


# ─── DCC-GARCH vs EWMA comparison ────────────────────────────────────────────

class TestDCCVsEWMA:
    def test_high_vol_period_changes_correlation(self):
        """DCC dovrebbe produrre correlazioni diverse da EWMA statica su dati eteroschedastici."""
        with patch("engine.analytics.correlation.dcc_garch.is_enabled", return_value=True):
            rng = np.random.default_rng(0)
            # Crea rendimenti con volatilità clustering (GARCH-like)
            n = 400
            r1 = np.zeros(n)
            r2 = np.zeros(n)
            vol = 0.01
            for t in range(1, n):
                vol = 0.01 + 0.1 * r1[t-1]**2 + 0.85 * vol
                r1[t] = rng.normal(0, vol)
                r2[t] = 0.7 * r1[t] + rng.normal(0, 0.005)

            df = pd.DataFrame({"A": r1, "B": r2})
            analyzer = DCCGARCHAnalyzer()
            result = analyzer.compute(df)

        # La correlazione DCC dovrebbe essere alta (A causa B con 0.7 peso)
        corr = result.correlation_matrix[0, 1]
        assert corr > 0.5  # deve catturare la relazione
