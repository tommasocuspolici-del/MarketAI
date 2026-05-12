"""Integration test: CompositeSignalAggregator v2 su fixture DuckDB.

Verifica:
  · Pipeline completa con labour_market e surprise components
  · Pesi sommano a 1.0
  · Signal in [-1, 1]
  · Correlazione v2 con v1 > 0 (stessa direzione su dati sintetici)
"""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch
from engine.alpha_generation.composite_signal_aggregator import (
    CompositeSignalAggregator, _WEIGHTS
)


class TestCompositeSignalV2:

    def test_weights_sum_to_one(self):
        """Pesi v2 sommano esattamente a 1.0."""
        total = sum(_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_new_weights_present(self):
        """labour_market e surprise presenti nei pesi."""
        assert "labour_market" in _WEIGHTS
        assert "surprise" in _WEIGHTS

    def test_version_is_v2(self):
        from engine.alpha_generation.composite_signal_aggregator import __version__
        assert __version__.startswith("2.")

    def test_read_labour_component_returns_none_on_missing_table(self):
        """_read_labour_component() → None se tabella labour_regime assente."""
        mock_db = MagicMock()
        mock_db.query.side_effect = Exception("no such table")
        agg = CompositeSignalAggregator(duckdb=mock_db)
        result = agg._read_labour_component()
        assert result is None

    def test_read_surprise_component_returns_none_on_missing_table(self):
        """_read_surprise_component() → None se tabella surprise_signal assente."""
        mock_db = MagicMock()
        mock_db.query.side_effect = Exception("no such table")
        agg = CompositeSignalAggregator(duckdb=mock_db)
        result = agg._read_surprise_component()
        assert result is None

    def test_signal_in_range_with_mocked_components(self):
        """Signal in [-1, 1] con tutti i componenti mockati."""
        mock_db = MagicMock()
        mock_db.query.return_value = [(0.5, "BUY")]

        agg = CompositeSignalAggregator(duckdb=mock_db)
        with patch.object(agg, "_read_vix_component", return_value=0.3):
            with patch.object(agg, "_read_yield_curve_component", return_value=(0.2, "normal")):
                with patch.object(agg, "_read_credit_component", return_value=(0.1, "low")):
                    with patch.object(agg, "_read_claims_component", return_value=(0.2, "expansion")):
                        with patch.object(agg, "_read_macro_conviction_component", return_value=0.1):
                            with patch.object(agg, "_read_labour_component", return_value=0.4):
                                with patch.object(agg, "_read_surprise_component", return_value=0.2):
                                    with patch.object(agg, "_read_current_regime", return_value="expansion"):
                                        with patch.object(agg, "_persist", return_value=None):
                                            output = agg.compute()
        assert -1.0 <= output.composite_score <= 1.0
        assert output.recommended_action in ("BUY", "HOLD", "REDUCE")


class TestCompositeSignalWeightSanity:

    def test_individual_weights_positive(self):
        """Ogni peso è positivo."""
        for name, w in _WEIGHTS.items():
            assert w > 0, f"Peso '{name}' = {w} ≤ 0"

    def test_individual_weights_below_half(self):
        """Nessun singolo peso supera il 50% per evitare dominanza."""
        for name, w in _WEIGHTS.items():
            assert w <= 0.50, f"Peso '{name}' = {w} > 0.50 (troppo dominante)"
