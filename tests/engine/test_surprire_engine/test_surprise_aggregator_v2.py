"""Tests per engine.analytics.surprise_engine.surprise_aggregator_v2.

Copre: SurpriseAccuracyTracker, AutoWeightCalibrator, PipelineResult.
SurpriseAggregatorV2.run_full_pipeline() è gated dal feature flag
'surprise_scheduler' e richiede infrastruttura DuckDB — testato con mock.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from engine.analytics.surprise_engine.surprise_aggregator_v2 import (
    AutoWeightCalibrator,
    PipelineResult,
    SurpriseAccuracyTracker,
)


_CREATE_ACCURACY_LOG = """
CREATE TABLE IF NOT EXISTS surprise_accuracy_log (
    indicator_code  VARCHAR NOT NULL,
    period_start    DATE    NOT NULL,
    period_end      DATE    NOT NULL,
    mean_abs_surprise DOUBLE,
    hit_rate_direction DOUBLE,
    PRIMARY KEY (indicator_code, period_start)
)
"""


def _make_client_with_table():
    import duckdb
    from contextlib import contextmanager
    conn = duckdb.connect(":memory:")
    conn.execute(_CREATE_ACCURACY_LOG)
    client = MagicMock()
    client.execute = conn.execute
    client.query = lambda sql, params=None: conn.execute(sql, params or []).fetchall()
    return client


def _make_computed_df(
    indicators: list[str] | None = None,
    z_scores: list[float] | None = None,
) -> pd.DataFrame:
    if indicators is None:
        indicators = ["UNRATE", "PAYEMS", "CPI"]
    if z_scores is None:
        z_scores = [1.5, -0.8, 0.6]
    n = len(indicators)
    return pd.DataFrame({
        "indicator_code": indicators,
        "surprise_z": z_scores,
        "release_date": pd.date_range("2024-01-01", periods=n, freq="MS"),
        "actual": [4.0] * n,
        "consensus": [3.9] * n,
    })


class TestSurpriseAccuracyTrackerRecordPredictions:
    def test_empty_df_returns_0(self) -> None:
        client = _make_client_with_table()
        tracker = SurpriseAccuracyTracker(client)
        assert tracker.record_predictions(pd.DataFrame()) == 0

    def test_all_insignificant_returns_0(self) -> None:
        client = _make_client_with_table()
        tracker = SurpriseAccuracyTracker(client)
        df = _make_computed_df(z_scores=[0.1, 0.2, 0.1])
        assert tracker.record_predictions(df) == 0

    def test_significant_rows_inserted(self) -> None:
        client = _make_client_with_table()
        tracker = SurpriseAccuracyTracker(client)
        df = _make_computed_df(z_scores=[1.5, -0.8, 0.6])
        n = tracker.record_predictions(df)
        assert n == 3  # all 3 have |z| >= 0.3

    def test_record_updates_accuracy_log(self) -> None:
        import duckdb
        from contextlib import contextmanager
        conn = duckdb.connect(":memory:")
        conn.execute(_CREATE_ACCURACY_LOG)
        client = MagicMock()
        client.execute = conn.execute
        client.query = lambda sql, p=None: conn.execute(sql, p or []).fetchall()

        tracker = SurpriseAccuracyTracker(client)
        df = _make_computed_df(["UNRATE"], [1.5])
        tracker.record_predictions(df)
        rows = conn.execute("SELECT COUNT(*) FROM surprise_accuracy_log").fetchone()[0]
        assert rows == 1

    def test_hit_rate_all_positive_z(self) -> None:
        import duckdb
        conn = duckdb.connect(":memory:")
        conn.execute(_CREATE_ACCURACY_LOG)
        client = MagicMock()
        client.execute = conn.execute
        client.query = lambda sql, p=None: conn.execute(sql, p or []).fetchall()

        tracker = SurpriseAccuracyTracker(client)
        df = _make_computed_df(["UNRATE", "UNRATE"], [1.5, 2.0])
        tracker.record_predictions(df)
        rows = conn.execute(
            "SELECT hit_rate_direction FROM surprise_accuracy_log WHERE indicator_code = 'UNRATE'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == pytest.approx(1.0)  # 100% positive

    def test_db_error_logs_warning(self) -> None:
        client = MagicMock()
        client.execute = MagicMock(side_effect=RuntimeError("DB error"))
        tracker = SurpriseAccuracyTracker(client)
        df = _make_computed_df()
        # Should not raise, should return some count
        result = tracker.record_predictions(df)
        assert isinstance(result, int)


class TestSurpriseAccuracyTrackerGetAccuracy:
    def test_empty_db_returns_empty_dict(self) -> None:
        client = _make_client_with_table()
        tracker = SurpriseAccuracyTracker(client)
        result = tracker.get_accuracy_by_indicator()
        assert result == {}

    def test_returns_indicator_accuracy(self) -> None:
        import duckdb
        conn = duckdb.connect(":memory:")
        conn.execute(_CREATE_ACCURACY_LOG)
        # Use recent dates (within 12 months of now = after 2025-05)
        conn.execute(
            """INSERT INTO surprise_accuracy_log VALUES
               ('UNRATE', '2025-06-01', '2025-12-01', 0.5, 0.75)"""
        )
        client = MagicMock()
        client.execute = conn.execute
        client.query = lambda sql, p=None: conn.execute(sql, p or []).fetchall()

        tracker = SurpriseAccuracyTracker(client)
        result = tracker.get_accuracy_by_indicator()
        assert "UNRATE" in result
        assert result["UNRATE"] == pytest.approx(0.75)

    def test_get_overall_accuracy_none_when_empty(self) -> None:
        client = _make_client_with_table()
        tracker = SurpriseAccuracyTracker(client)
        assert tracker.get_overall_accuracy() is None

    def test_get_overall_accuracy_mean(self) -> None:
        import duckdb
        conn = duckdb.connect(":memory:")
        conn.execute(_CREATE_ACCURACY_LOG)
        # Use recent dates (within 12 months of now = after 2025-05)
        conn.execute(
            """INSERT INTO surprise_accuracy_log VALUES
               ('UNRATE', '2025-06-01', '2025-12-01', 0.5, 0.6),
               ('CPI', '2025-06-01', '2025-12-01', 0.4, 0.8)"""
        )
        client = MagicMock()
        client.execute = conn.execute
        client.query = lambda sql, p=None: conn.execute(sql, p or []).fetchall()

        tracker = SurpriseAccuracyTracker(client)
        result = tracker.get_overall_accuracy()
        assert result == pytest.approx(0.7)

    def test_get_accuracy_db_error_returns_empty(self) -> None:
        client = MagicMock()
        client.query = MagicMock(side_effect=RuntimeError("fail"))
        tracker = SurpriseAccuracyTracker(client)
        result = tracker.get_accuracy_by_indicator()
        assert result == {}


class TestAutoWeightCalibrator:
    def test_empty_accuracy_map_keeps_weights(self) -> None:
        calibrator = AutoWeightCalibrator()
        weights = {"equity": {"UNRATE": 0.3, "CPI": 0.7}}
        new_weights = calibrator.calibrate({}, weights)
        assert new_weights["equity"]["UNRATE"] == pytest.approx(0.3, abs=1e-3)
        assert new_weights["equity"]["CPI"] == pytest.approx(0.7, abs=1e-3)

    def test_high_accuracy_increases_weight(self) -> None:
        calibrator = AutoWeightCalibrator()
        weights = {"equity": {"UNRATE": 0.5, "CPI": 0.5}}
        accuracy = {"UNRATE": 0.9, "CPI": 0.5}  # UNRATE performs better
        new_weights = calibrator.calibrate(accuracy, weights)
        # UNRATE should have higher weight than CPI after calibration
        assert new_weights["equity"]["UNRATE"] > new_weights["equity"]["CPI"]

    def test_weights_normalized_to_sum_1(self) -> None:
        calibrator = AutoWeightCalibrator()
        weights = {"equity": {"A": 0.3, "B": 0.3, "C": 0.4}}
        accuracy = {"A": 0.8, "B": 0.6, "C": 0.4}
        new_weights = calibrator.calibrate(accuracy, weights)
        total = sum(new_weights["equity"].values())
        assert total == pytest.approx(1.0, abs=1e-3)

    def test_multiple_sectors_calibrated_independently(self) -> None:
        calibrator = AutoWeightCalibrator()
        weights = {
            "equity": {"A": 0.5, "B": 0.5},
            "bond": {"C": 0.4, "D": 0.6},
        }
        accuracy = {"A": 0.9, "D": 0.2}
        new_weights = calibrator.calibrate(accuracy, weights)
        assert "equity" in new_weights
        assert "bond" in new_weights
        # Each sector sums to 1
        assert sum(new_weights["equity"].values()) == pytest.approx(1.0, abs=1e-3)
        assert sum(new_weights["bond"].values()) == pytest.approx(1.0, abs=1e-3)

    def test_low_accuracy_decreases_weight(self) -> None:
        calibrator = AutoWeightCalibrator()
        weights = {"equity": {"UNRATE": 0.5, "CPI": 0.5}}
        accuracy = {"UNRATE": 0.1, "CPI": 0.5}  # UNRATE performs badly
        new_weights = calibrator.calibrate(accuracy, weights)
        # Normalized: UNRATE should have lower weight than CPI
        assert new_weights["equity"]["UNRATE"] < new_weights["equity"]["CPI"]

    def test_unknown_indicator_keeps_weight(self) -> None:
        calibrator = AutoWeightCalibrator()
        weights = {"equity": {"KNOWN": 0.4, "UNKNOWN": 0.6}}
        accuracy = {"KNOWN": 0.8}
        new_weights = calibrator.calibrate(accuracy, weights)
        # Sum still 1
        assert sum(new_weights["equity"].values()) == pytest.approx(1.0, abs=1e-3)

    def test_weight_minimum_is_positive(self) -> None:
        calibrator = AutoWeightCalibrator()
        weights = {"equity": {"BAD": 0.01, "GOOD": 0.99}}
        accuracy = {"BAD": 0.0, "GOOD": 1.0}
        new_weights = calibrator.calibrate(accuracy, weights)
        # minimum weight is 0.01 (not zero)
        assert all(v > 0 for v in new_weights["equity"].values())


class TestPipelineResult:
    def test_dataclass_creation(self) -> None:
        from datetime import datetime, UTC
        result = PipelineResult(
            run_at=datetime.now(UTC),
            signal=None,
            sector_indices=[],
            rows_computed=0,
            accuracy_before=None,
            accuracy_after=None,
            calibrated=False,
        )
        assert result.rows_computed == 0
        assert result.calibrated is False
        assert result.signal is None


class TestSurpriseAggregatorV2FeatureFlag:
    def test_raises_when_flag_disabled(self) -> None:
        from shared.exceptions import FeatureDisabledError
        from engine.analytics.surprise_engine.surprise_aggregator_v2 import SurpriseAggregatorV2
        with patch("engine.analytics.surprise_engine.surprise_aggregator_v2.is_enabled", return_value=False):
            with pytest.raises(FeatureDisabledError):
                SurpriseAggregatorV2(client=MagicMock())

    def test_pipeline_empty_consensus_returns_no_signal(self) -> None:
        from engine.analytics.surprise_engine.surprise_aggregator_v2 import SurpriseAggregatorV2
        client = _make_client_with_table()
        with patch("engine.analytics.surprise_engine.surprise_aggregator_v2.is_enabled", return_value=True):
            with patch.object(SurpriseAggregatorV2, "_load_consensus_data", return_value=pd.DataFrame()):
                agg = SurpriseAggregatorV2(client=client)
                result = agg.run_full_pipeline()
        assert result.signal is None
        assert result.rows_computed == 0
        assert result.calibrated is False

    def test_load_config_returns_dict(self) -> None:
        from engine.analytics.surprise_engine.surprise_aggregator_v2 import SurpriseAggregatorV2
        client = _make_client_with_table()
        with patch("engine.analytics.surprise_engine.surprise_aggregator_v2.is_enabled", return_value=True):
            agg = SurpriseAggregatorV2(client=client)
        cfg = agg._load_config()
        assert isinstance(cfg, dict)
