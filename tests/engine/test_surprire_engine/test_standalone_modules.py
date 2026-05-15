"""Tests per i moduli standalone del Surprise Engine (Blocco 2 ROADMAP v4).

Verifica che surprise_calculator.py, sector_surprise_aggregator.py e
surprise_signal_generator.py re-esportino correttamente le classi da
surprise_engine.py e che SurpriseAccuracyTracker usi lo schema corretto.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest


# ─── Standalone module imports ────────────────────────────────────────────────

class TestStandaloneModuleImports:
    def test_surprise_calculator_importable(self):
        from engine.analytics.surprise_engine.surprise_calculator import (
            SurpriseCalculator, IndicatorSurprise,
        )
        assert SurpriseCalculator is not None
        assert IndicatorSurprise is not None

    def test_sector_surprise_aggregator_importable(self):
        from engine.analytics.surprise_engine.sector_surprise_aggregator import (
            SectorSurpriseAggregator, SectorSurpriseIndex, SECTOR_WEIGHTS,
        )
        assert SectorSurpriseAggregator is not None
        assert isinstance(SECTOR_WEIGHTS, dict)

    def test_surprise_signal_generator_importable(self):
        from engine.analytics.surprise_engine.surprise_signal_generator import (
            SurpriseSignalGenerator, SurpriseCompositeSignal,
        )
        assert SurpriseSignalGenerator is not None
        assert SurpriseCompositeSignal is not None

    def test_same_class_as_surprise_engine(self):
        """I moduli standalone re-esportano le stesse classi di surprise_engine."""
        from engine.analytics.surprise_engine.surprise_calculator import SurpriseCalculator as SC1
        from engine.analytics.surprise_engine.surprise_engine import SurpriseCalculator as SC2
        assert SC1 is SC2

    def test_sector_weights_sum_to_one(self):
        from engine.analytics.surprise_engine.sector_surprise_aggregator import SECTOR_WEIGHTS
        assert abs(sum(SECTOR_WEIGHTS.values()) - 1.0) < 1e-6

    def test_init_exports_all_classes(self):
        """__init__.py esporta tutte le classi chiave."""
        from engine.analytics.surprise_engine import (
            SurpriseCalculator, SectorSurpriseAggregator, SurpriseSignalGenerator,
            SurpriseMomentum, ConsensusLoader, SurpriseAggregatorV2,
            SurpriseAccuracyTracker, AutoWeightCalibrator, PipelineResult,
        )
        for cls in [SurpriseCalculator, SectorSurpriseAggregator, SurpriseSignalGenerator,
                    SurpriseMomentum, SurpriseAggregatorV2]:
            assert cls is not None


# ─── SurpriseAccuracyTracker schema fix ───────────────────────────────────────

def _make_computed_df(n: int = 10) -> pd.DataFrame:
    """DataFrame simulato da SurpriseCalculator.compute_from_df()."""
    dates = pd.date_range("2024-01-01", periods=n, freq="MS")
    return pd.DataFrame({
        "release_date":   dates,
        "indicator_code": ["NFP"] * (n // 2) + ["CPI"] * (n - n // 2),
        "sector":         ["labour"] * (n // 2) + ["inflation"] * (n - n // 2),
        "surprise_z":     np.linspace(-2.0, 2.0, n),
        "surprise_raw":   np.linspace(-50.0, 50.0, n),
    })


class TestAccuracyTrackerSchemaFix:
    @pytest.fixture()
    def mock_client(self):
        client = MagicMock()
        client.query.return_value = []
        client.execute.return_value = None
        return client

    @pytest.fixture()
    def tracker(self, mock_client):
        from engine.analytics.surprise_engine.surprise_aggregator_v2 import SurpriseAccuracyTracker
        return SurpriseAccuracyTracker(client=mock_client)

    def test_record_predictions_returns_int(self, tracker):
        df = _make_computed_df(10)
        result = tracker.record_predictions(df)
        assert isinstance(result, int)
        assert result >= 0

    def test_record_predictions_returns_zero_on_empty(self, tracker):
        assert tracker.record_predictions(pd.DataFrame()) == 0

    def test_record_predictions_calls_execute(self, tracker, mock_client):
        """Deve chiamare execute() con le colonne dello schema corretto."""
        df = _make_computed_df(10)
        tracker.record_predictions(df)
        # Deve aver chiamato execute almeno una volta (per ogni indicatore)
        assert mock_client.execute.called
        # Verifica che le colonne usate siano quelle del schema migration 010
        call_args = mock_client.execute.call_args_list[0][0][0]
        assert "hit_rate_direction" in call_args
        assert "mean_abs_surprise" in call_args
        assert "period_start" in call_args
        assert "period_end" in call_args
        # NON devono esserci le colonne del vecchio schema
        assert "predicted_beat" not in call_args
        assert "outcome_beat" not in call_args
        assert "recorded_at" not in call_args

    def test_record_predictions_filters_marginal_z(self, tracker, mock_client):
        """z-score < 0.3 non deve essere incluso."""
        df = pd.DataFrame({
            "release_date":   pd.date_range("2024-01-01", periods=5, freq="MS"),
            "indicator_code": ["NFP"] * 5,
            "sector":         ["labour"] * 5,
            "surprise_z":     [0.1, 0.2, 0.05, 0.15, 0.1],  # tutti < 0.3
        })
        result = tracker.record_predictions(df)
        assert result == 0
        mock_client.execute.assert_not_called()

    def test_get_accuracy_uses_hit_rate_direction(self, tracker, mock_client):
        """get_accuracy_by_indicator usa hit_rate_direction (non outcome_beat)."""
        mock_client.query.return_value = [
            ("NFP", 0.65),
            ("CPI", 0.58),
        ]
        result = tracker.get_accuracy_by_indicator()
        assert "NFP" in result
        assert result["NFP"] == pytest.approx(0.65, abs=0.001)
        # Verifica che la query NON menzioni outcome_beat
        call_sql = mock_client.query.call_args[0][0]
        assert "outcome_beat" not in call_sql
        assert "hit_rate_direction" in call_sql

    def test_get_accuracy_returns_empty_on_db_error(self, tracker, mock_client):
        mock_client.query.side_effect = Exception("table not found")
        result = tracker.get_accuracy_by_indicator()
        assert result == {}

    def test_get_overall_accuracy_mean(self, tracker, mock_client):
        mock_client.query.return_value = [("NFP", 0.60), ("CPI", 0.70)]
        result = tracker.get_overall_accuracy()
        assert result == pytest.approx(0.65, abs=0.01)

    def test_get_overall_accuracy_none_when_empty(self, tracker, mock_client):
        mock_client.query.return_value = []
        assert tracker.get_overall_accuracy() is None

    def test_record_predictions_aggregates_by_indicator(self, tracker, mock_client):
        """Raggruppa per indicator_code, non per riga."""
        # 6 righe per 2 indicatori → execute chiamato 2 volte
        df = _make_computed_df(12)
        tracker.record_predictions(df)
        # Una chiamata per NFP, una per CPI
        assert mock_client.execute.call_count == 2

    def test_hit_rate_direction_computation(self, tracker, mock_client):
        """Calcola hit_rate_direction come % di z > 0."""
        df = pd.DataFrame({
            "release_date":   pd.date_range("2024-01-01", periods=4, freq="MS"),
            "indicator_code": ["NFP"] * 4,
            "sector":         ["labour"] * 4,
            "surprise_z":     [1.5, 2.0, -0.8, 1.2],  # 3 beat, 1 miss → 75%
        })
        tracker.record_predictions(df)
        # Estrai i parametri della chiamata execute
        call_params = mock_client.execute.call_args[0][1]
        hit_rate = call_params[4]  # 5° elemento: hit_rate_direction
        assert hit_rate == pytest.approx(0.75, abs=0.01)


# ─── Scheduler job re-run (integrazione) ─────────────────────────────────────

class TestSchedulerJobNoLongerCrashes:
    def test_surprise_consensus_loader_imports_work(self):
        """ConsensusLoader importabile e istanziabile con mock client."""
        from engine.analytics.surprise_engine.consensus_loader import ConsensusLoader
        mock_client = MagicMock()
        mock_client.query.return_value = []
        # Non deve sollevare eccezioni durante l'importazione
        assert ConsensusLoader is not None

    def test_accuracy_tracker_no_outcome_beat_reference(self):
        """Verifica che il codice sorgente non contenga più 'outcome_beat'."""
        import inspect
        from engine.analytics.surprise_engine import surprise_aggregator_v2 as mod
        source = inspect.getsource(mod.SurpriseAccuracyTracker)
        assert "outcome_beat" not in source, (
            "SurpriseAccuracyTracker contiene ancora 'outcome_beat' "
            "che non esiste nella tabella surprise_accuracy_log"
        )
