"""Tests per engine.market_data.silent_failure_detector — SilentFailureDetector v2."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from engine.market_data.silent_failure_detector import SilentFailureDetector, SilentFailureResult


def _make_ohlcv(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    data: dict[str, object] = {
        "ts": pd.date_range("2024-01-01", periods=n, freq="B"),
        "close": closes,
    }
    if volumes is not None:
        data["volume"] = volumes
    return pd.DataFrame(data)


@pytest.fixture
def detector() -> SilentFailureDetector:
    return SilentFailureDetector(stale_window=3, zero_vol_window=2)


class TestCheckOhlcvMissing:
    def test_none_df_returns_missing(self, detector) -> None:
        r = detector.check_ohlcv(None, "^VIX")  # type: ignore[arg-type]
        assert r.failure_detected is True
        assert r.failure_type == "missing"
        assert r.quality_score == pytest.approx(0.0)

    def test_empty_df_returns_missing(self, detector) -> None:
        r = detector.check_ohlcv(pd.DataFrame(), "^VIX")
        assert r.failure_detected is True
        assert r.failure_type == "missing"

    def test_all_nan_closes_returns_missing(self, detector) -> None:
        df = pd.DataFrame({"ts": ["2024-01-01"], "close": [float("nan")]})
        r = detector.check_ohlcv(df, "^VIX")
        assert r.failure_detected is True
        assert r.failure_type == "missing"


class TestCheckOhlcvStale:
    def test_same_value_3_days_is_stale(self, detector) -> None:
        r = detector.check_ohlcv(_make_ohlcv([18.0, 18.0, 18.0]), "^VIX")
        assert r.failure_detected is True
        assert r.failure_type == "stale"
        assert 0.1 <= r.quality_score < 1.0

    def test_varying_values_is_ok(self, detector) -> None:
        r = detector.check_ohlcv(_make_ohlcv([16.0, 17.0, 18.0, 19.0]), "^VIX")
        assert r.failure_detected is False
        assert r.failure_type is None
        assert r.quality_score == pytest.approx(1.0)

    def test_latest_value_stored(self, detector) -> None:
        r = detector.check_ohlcv(_make_ohlcv([15.0, 16.0, 17.0]), "^VIX")
        assert r.latest_value == pytest.approx(17.0)

    def test_series_id_preserved(self, detector) -> None:
        r = detector.check_ohlcv(_make_ohlcv([17.0, 18.0, 19.0]), "MY_SERIES")
        assert r.series_id == "MY_SERIES"

    def test_stale_quality_score_is_positive(self, detector) -> None:
        r = detector.check_ohlcv(_make_ohlcv([20.0, 20.0, 20.0]), "^VIX")
        assert r.quality_score >= 0.1


class TestCheckOhlcvZeroVolume:
    def test_zero_volume_2_days_detected(self, detector) -> None:
        r = detector.check_ohlcv(
            _make_ohlcv([17.0, 18.0, 19.0], volumes=[1000.0, 0.0, 0.0]),
            "CL=F",
        )
        assert r.failure_detected is True
        assert r.failure_type == "zero_volume"
        assert r.quality_score == pytest.approx(0.4)

    def test_one_zero_volume_not_detected(self, detector) -> None:
        r = detector.check_ohlcv(
            _make_ohlcv([17.0, 18.0, 19.0], volumes=[1000.0, 1000.0, 0.0]),
            "CL=F",
        )
        assert r.failure_type != "zero_volume"

    def test_no_volume_column_skips_check(self, detector) -> None:
        r = detector.check_ohlcv(_make_ohlcv([17.0, 18.0, 19.0]), "^VIX")
        assert r.failure_type != "zero_volume"


class TestCheckMacroSeries:
    def _make_macro_df(self, days_ago: int, value: float = 5.0) -> pd.DataFrame:
        ts = datetime.now(UTC) - timedelta(days=days_ago)
        return pd.DataFrame({"ts": [ts], "value": [value]})

    def test_recent_series_ok(self, detector) -> None:
        df = self._make_macro_df(days_ago=5)
        r = detector.check_macro_series(df, "UNRATE")
        assert r.failure_detected is False
        assert r.quality_score == pytest.approx(1.0)

    def test_stale_series_detected(self, detector) -> None:
        df = self._make_macro_df(days_ago=40)
        r = detector.check_macro_series(df, "CPIAUCSL", max_stale_days=35)
        assert r.failure_detected is True
        assert r.failure_type == "stale"
        assert r.quality_score == pytest.approx(0.5)

    def test_empty_df_missing(self, detector) -> None:
        r = detector.check_macro_series(pd.DataFrame(), "UNRATE")
        assert r.failure_detected is True
        assert r.failure_type == "missing"

    def test_none_df_missing(self, detector) -> None:
        r = detector.check_macro_series(None, "UNRATE")  # type: ignore[arg-type]
        assert r.failure_detected is True

    def test_latest_value_stored(self, detector) -> None:
        df = self._make_macro_df(days_ago=5, value=3.7)
        r = detector.check_macro_series(df, "UNRATE")
        assert r.latest_value == pytest.approx(3.7)

    def test_all_nan_values_missing(self, detector) -> None:
        df = pd.DataFrame({"ts": [datetime.now(UTC)], "value": [float("nan")]})
        r = detector.check_macro_series(df, "UNRATE")
        assert r.failure_detected is True
        assert r.failure_type == "missing"

    def test_first_column_used_as_fallback(self, detector) -> None:
        df = pd.DataFrame({"date": [datetime.now(UTC)], "val": [4.2]})
        r = detector.check_macro_series(df, "UNRATE")
        assert r.latest_value == pytest.approx(4.2)


class TestSilentFailureResult:
    def test_frozen(self) -> None:
        r = SilentFailureResult(
            series_id="X", failure_detected=False, failure_type=None,
            stale_days=0, latest_value=1.0, quality_score=1.0, message="ok",
        )
        with pytest.raises((AttributeError, TypeError)):
            r.failure_detected = True  # type: ignore[misc]

    def test_no_failure_message_contains_ok(self, detector) -> None:
        r = detector.check_ohlcv(_make_ohlcv([15.0, 16.0, 17.0]), "TEST")
        assert "OK" in r.message or "nessun" in r.message.lower()


class TestCustomWindows:
    def test_custom_stale_window_2(self) -> None:
        det = SilentFailureDetector(stale_window=2, zero_vol_window=2)
        r = det.check_ohlcv(_make_ohlcv([18.0, 18.0]), "^VIX")
        assert r.failure_detected is True
        assert r.failure_type == "stale"

    def test_custom_stale_window_5_not_triggered(self) -> None:
        det = SilentFailureDetector(stale_window=5, zero_vol_window=2)
        r = det.check_ohlcv(_make_ohlcv([18.0, 18.0, 18.0]), "^VIX")
        assert r.failure_detected is False
