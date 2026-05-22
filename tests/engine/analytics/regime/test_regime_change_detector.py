from __future__ import annotations

import pytest
import numpy as np
import pandas as pd
from datetime import date

from engine.analytics.regime.regime_change_detector import (
    RegimeChangeDetector,
    ChangePoint,
    CUSUM_THRESHOLD,
    MIN_SERIES_LENGTH,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def detector() -> RegimeChangeDetector:
    return RegimeChangeDetector()


def _make_datetime_index(n: int, start: str = "2020-01-01") -> pd.DatetimeIndex:
    return pd.date_range(start=start, periods=n, freq="D", tz="UTC")


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

class TestInstantiation:
    def test_default_threshold(self) -> None:
        det = RegimeChangeDetector()
        assert det._threshold == CUSUM_THRESHOLD

    def test_custom_threshold(self) -> None:
        det = RegimeChangeDetector(threshold=3.0)
        assert det._threshold == 3.0


# ---------------------------------------------------------------------------
# cusum_detect
# ---------------------------------------------------------------------------

class TestCusumDetect:
    def test_returns_list(self, detector: RegimeChangeDetector) -> None:
        idx = _make_datetime_index(50)
        series = pd.Series(np.zeros(50), index=idx)
        result = detector.cusum_detect(series, "test")
        assert isinstance(result, list)

    def test_too_short_series_returns_empty(self, detector: RegimeChangeDetector) -> None:
        idx = _make_datetime_index(MIN_SERIES_LENGTH - 1)
        series = pd.Series(np.ones(MIN_SERIES_LENGTH - 1), index=idx)
        result = detector.cusum_detect(series, "short")
        assert result == []

    def test_constant_series_returns_empty(self, detector: RegimeChangeDetector) -> None:
        idx = _make_datetime_index(100)
        series = pd.Series(np.ones(100) * 3.0, index=idx)
        result = detector.cusum_detect(series, "constant")
        assert result == []

    def test_flat_noisy_series_no_significant_change(self) -> None:
        rng = np.random.default_rng(42)
        idx = _make_datetime_index(200)
        # Tight noise: very small std → CUSUM unlikely to exceed high threshold
        series = pd.Series(rng.normal(0.0, 0.001, 200), index=idx)
        det = RegimeChangeDetector(threshold=100.0)  # extremely high threshold
        result = det.cusum_detect(series, "flat")
        assert result == []

    def test_step_change_detects_changepoint(self) -> None:
        """A series that jumps from 0 to 5 at midpoint should detect at least one ChangePoint."""
        rng = np.random.default_rng(42)
        n = 200
        idx = _make_datetime_index(n)
        values = np.concatenate([
            rng.normal(0.0, 0.1, n // 2),
            rng.normal(5.0, 0.1, n // 2),
        ])
        series = pd.Series(values, index=idx)
        det = RegimeChangeDetector(threshold=2.0)  # lower threshold for test
        result = det.cusum_detect(series, "step_change")
        assert len(result) >= 1

    def test_changepoint_is_significant(self) -> None:
        rng = np.random.default_rng(42)
        n = 200
        idx = _make_datetime_index(n)
        values = np.concatenate([
            rng.normal(0.0, 0.05, n // 2),
            rng.normal(10.0, 0.05, n // 2),
        ])
        series = pd.Series(values, index=idx)
        det = RegimeChangeDetector(threshold=1.0)
        result = det.cusum_detect(series, "step_change_sig")
        assert all(cp.is_significant for cp in result)

    def test_changepoint_fields(self) -> None:
        rng = np.random.default_rng(42)
        n = 200
        idx = _make_datetime_index(n)
        values = np.concatenate([
            rng.normal(0.0, 0.05, n // 2),
            rng.normal(8.0, 0.05, n // 2),
        ])
        series = pd.Series(values, index=idx)
        det = RegimeChangeDetector(threshold=1.0)
        result = det.cusum_detect(series, "my_series")
        assert len(result) >= 1
        cp = result[0]
        assert isinstance(cp, ChangePoint)
        assert isinstance(cp.detected_date, date)
        assert isinstance(cp.cusum_value, float)
        assert cp.cusum_value > 0
        assert cp.signal_series == "my_series"
        assert cp.is_significant is True

    def test_series_without_tz(self, detector: RegimeChangeDetector) -> None:
        """Series with naive DatetimeIndex should not crash."""
        idx = pd.date_range("2020-01-01", periods=50, freq="D")
        rng = np.random.default_rng(0)
        series = pd.Series(rng.normal(0, 0.1, 50), index=idx)
        result = detector.cusum_detect(series, "naive_idx")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# detect_on_regime_probs
# ---------------------------------------------------------------------------

class TestDetectOnRegimeProbs:
    def test_empty_dataframe_returns_empty(self, detector: RegimeChangeDetector) -> None:
        df = pd.DataFrame()
        result = detector.detect_on_regime_probs(df)
        assert result == []

    def test_no_prob_columns_returns_empty(self, detector: RegimeChangeDetector) -> None:
        df = pd.DataFrame({"regime_label": ["expansion"] * 20})
        result = detector.detect_on_regime_probs(df)
        assert result == []

    def test_accepts_prob_expansion_column(self, detector: RegimeChangeDetector) -> None:
        rng = np.random.default_rng(42)
        n = 50
        dates = pd.date_range("2020-01-01", periods=n, freq="ME")
        df = pd.DataFrame({
            "snapshot_date": dates,
            "prob_expansion": rng.uniform(0.3, 0.9, n),
            "prob_contraction": rng.uniform(0.1, 0.5, n),
        })
        result = detector.detect_on_regime_probs(df)
        assert isinstance(result, list)

    def test_returns_list_of_changepoints(self, detector: RegimeChangeDetector) -> None:
        rng = np.random.default_rng(99)
        n = 60
        dates = pd.date_range("2018-01-01", periods=n, freq="ME")
        # Step change in prob_expansion at midpoint
        probs = np.concatenate([
            rng.normal(0.8, 0.01, n // 2),
            rng.normal(0.2, 0.01, n // 2),
        ])
        df = pd.DataFrame({
            "snapshot_date": dates,
            "prob_expansion": np.clip(probs, 0, 1),
        })
        det = RegimeChangeDetector(threshold=1.0)
        result = det.detect_on_regime_probs(df)
        assert isinstance(result, list)
        for cp in result:
            assert isinstance(cp, ChangePoint)

    def test_without_snapshot_date_column(self, detector: RegimeChangeDetector) -> None:
        rng = np.random.default_rng(7)
        n = 30
        dates = pd.date_range("2021-01-01", periods=n, freq="ME")
        df = pd.DataFrame(
            {"prob_expansion": rng.uniform(0.4, 0.8, n)},
            index=dates,
        )
        result = detector.detect_on_regime_probs(df)
        assert isinstance(result, list)
