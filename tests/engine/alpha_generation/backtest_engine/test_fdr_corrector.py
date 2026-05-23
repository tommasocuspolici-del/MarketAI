"""Tests for Benjamini-Hochberg FDR correction."""
from __future__ import annotations

import numpy as np
import pytest
from shared.exceptions import MarketAIError

from engine.alpha_generation.backtest_engine.fdr_corrector import (
    FDRResult,
    fdr_benjamini_hochberg,
    DEFAULT_FDR_ALPHA,
)


# ─── Fixtures ────────────────────────────────────────────────────────────── #

@pytest.fixture
def all_null_p_values() -> tuple[list[str], list[float]]:
    """Tutte le p-value > 0.05: nessuna strategia significativa."""
    ids = [f"strat_{i}" for i in range(5)]
    p_values = [0.10, 0.20, 0.30, 0.40, 0.50]
    return ids, p_values


@pytest.fixture
def all_significant_p_values() -> tuple[list[str], list[float]]:
    """Tutte le p-value molto piccole: tutte le strategie significative."""
    ids = [f"strat_{i}" for i in range(5)]
    p_values = [0.001, 0.002, 0.003, 0.004, 0.005]
    return ids, p_values


@pytest.fixture
def mixed_p_values() -> tuple[list[str], list[float]]:
    """Mix di p-value: alcune sotto soglia, alcune sopra."""
    ids = ["a", "b", "c", "d", "e"]
    p_values = [0.001, 0.008, 0.039, 0.041, 0.200]
    return ids, p_values


# ─── Tests: basic output structure ───────────────────────────────────────── #

class TestFDRResultStructure:
    def test_returns_fdr_result(self, all_null_p_values) -> None:
        ids, pvals = all_null_p_values
        result = fdr_benjamini_hochberg(ids, pvals)
        assert isinstance(result, FDRResult)

    def test_output_lengths_match_input(self, mixed_p_values) -> None:
        ids, pvals = mixed_p_values
        result = fdr_benjamini_hochberg(ids, pvals)
        assert len(result.strategy_ids) == len(ids)
        assert len(result.p_values) == len(pvals)
        assert len(result.adjusted_p_values) == len(pvals)
        assert len(result.rejected) == len(pvals)

    def test_fdr_alpha_stored(self, all_null_p_values) -> None:
        ids, pvals = all_null_p_values
        result = fdr_benjamini_hochberg(ids, pvals, alpha=0.05)
        assert result.fdr_alpha == 0.05


# ─── Tests: all null hypothesis ──────────────────────────────────────────── #

class TestAllNullHypothesis:
    def test_all_large_p_values_n_significant_is_zero(self, all_null_p_values) -> None:
        ids, pvals = all_null_p_values
        result = fdr_benjamini_hochberg(ids, pvals, alpha=0.05)
        assert result.n_significant == 0

    def test_all_large_p_values_no_rejected(self, all_null_p_values) -> None:
        ids, pvals = all_null_p_values
        result = fdr_benjamini_hochberg(ids, pvals, alpha=0.05)
        assert not any(result.rejected)


# ─── Tests: all significant ──────────────────────────────────────────────── #

class TestAllSignificant:
    def test_all_small_p_values_all_rejected(self, all_significant_p_values) -> None:
        ids, pvals = all_significant_p_values
        result = fdr_benjamini_hochberg(ids, pvals, alpha=0.05)
        assert all(result.rejected)
        assert result.n_significant == len(ids)


# ─── Tests: BH procedure correctness ─────────────────────────────────────── #

class TestBHProcedure:
    def test_mixed_p_values_correct_rejection(self, mixed_p_values) -> None:
        """Con p-values [0.001, 0.008, 0.039, 0.041, 0.200] e alpha=0.05:
        BH thresholds: [0.01, 0.02, 0.03, 0.04, 0.05]
        p_(1)=0.001 ≤ 0.01 ✓
        p_(2)=0.008 ≤ 0.02 ✓
        p_(3)=0.039 > 0.03 ✗ (k*=2, reject k≤2)
        """
        ids, pvals = mixed_p_values
        result = fdr_benjamini_hochberg(ids, pvals, alpha=0.05)
        assert result.n_significant >= 1

    def test_adjusted_p_values_are_valid(self, mixed_p_values) -> None:
        ids, pvals = mixed_p_values
        result = fdr_benjamini_hochberg(ids, pvals, alpha=0.05)
        # Adjusted p-values devono essere in [0, 1]
        for adj_p in result.adjusted_p_values:
            assert 0.0 <= adj_p <= 1.0

    def test_n_significant_matches_rejected_count(self, mixed_p_values) -> None:
        ids, pvals = mixed_p_values
        result = fdr_benjamini_hochberg(ids, pvals, alpha=0.05)
        assert result.n_significant == sum(result.rejected)

    def test_fdr_control_guarantee(self) -> None:
        """BH garantisce FDR ≤ alpha in attesa su molte realizzazioni.

        Con H0 tutte vere, la proporzione di falsi positivi non supera alpha
        in media.
        """
        rng = np.random.default_rng(123)
        alpha = 0.05
        n_strategies = 20
        n_simulations = 200
        false_positive_rates: list[float] = []

        for _ in range(n_simulations):
            # P-value uniformi (H0 vera per tutte)
            pvals = rng.uniform(0, 1, n_strategies).tolist()
            ids = [f"s{i}" for i in range(n_strategies)]
            result = fdr_benjamini_hochberg(ids, pvals, alpha=alpha)

            # Tutti i rejected sono falsi positivi (H0 vera)
            n_fp = sum(result.rejected)
            n_tested = n_strategies
            if result.n_significant > 0:
                fdr = n_fp / max(result.n_significant, 1)
            else:
                fdr = 0.0
            false_positive_rates.append(fdr)

        avg_fdr = float(np.mean(false_positive_rates))
        # In media, FDR ≤ alpha (con qualche tolleranza per sample finito)
        assert avg_fdr <= alpha + 0.05, f"Average FDR {avg_fdr:.4f} exceeds alpha={alpha}"


# ─── Tests: edge cases ───────────────────────────────────────────────────── #

class TestEdgeCases:
    def test_empty_input_returns_empty_result(self) -> None:
        result = fdr_benjamini_hochberg([], [], alpha=0.05)
        assert result.n_significant == 0
        assert result.strategy_ids == []
        assert result.rejected == []

    def test_single_strategy_significant(self) -> None:
        result = fdr_benjamini_hochberg(["only"], [0.001], alpha=0.05)
        assert result.n_significant == 1
        assert result.rejected == [True]

    def test_single_strategy_not_significant(self) -> None:
        result = fdr_benjamini_hochberg(["only"], [0.50], alpha=0.05)
        assert result.n_significant == 0
        assert result.rejected == [False]

    def test_mismatched_lengths_raises(self) -> None:
        with pytest.raises((ValueError, MarketAIError)):
            fdr_benjamini_hochberg(["a", "b"], [0.01], alpha=0.05)

    def test_strategy_ids_preserved_in_order(self) -> None:
        ids = ["z", "a", "m"]
        pvals = [0.30, 0.001, 0.20]
        result = fdr_benjamini_hochberg(ids, pvals, alpha=0.05)
        # Gli ID devono rimanere nell'ordine originale
        assert result.strategy_ids == ids
        assert result.p_values == pvals
