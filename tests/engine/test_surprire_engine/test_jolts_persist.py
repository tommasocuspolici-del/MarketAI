"""Tests for JOLTSAnalyzer._persist path and _compute_signal branches."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from engine.analytics.labour_market.jolts_analyzer import JOLTSAnalyzer, JOLTSSignal
from engine.market_data.fred_simple_client import FredSimpleClient, FredKeyMissingError


def _make_fred_df(values: list[float], start: str = "2023-01-01", freq: str = "MS") -> pd.DataFrame:
    dates = pd.date_range(start, periods=len(values), freq=freq)
    return pd.DataFrame({"ts": dates, "value": values})


class TestJOLTSAnalyzerPersist:
    def _analyzer_with_mock_fred(self, db=None, values=None):
        a = JOLTSAnalyzer(duckdb=db)
        df = _make_fred_df(values or [5.5, 5.8, 5.4, 5.6, 5.7, 5.2])

        def side_effect(series_id, **kwargs):
            return df.copy()

        a._client = MagicMock(spec=FredSimpleClient)
        a._client.fetch_series.side_effect = side_effect
        return a

    def test_analyze_calls_persist_when_db_provided(self):
        db = MagicMock()
        a = self._analyzer_with_mock_fred(db=db)
        result = a.analyze()
        assert isinstance(result, JOLTSSignal)
        assert db.execute.called

    def test_analyze_no_crash_without_db(self):
        a = self._analyzer_with_mock_fred(db=None)
        result = a.analyze()
        assert isinstance(result, JOLTSSignal)

    def test_analyze_raises_on_key_missing(self):
        a = JOLTSAnalyzer(duckdb=None)
        a._client = MagicMock(spec=FredSimpleClient)
        a._client.fetch_series.side_effect = FredKeyMissingError("no key")
        with pytest.raises(FredKeyMissingError):
            a.analyze()

    def test_labour_score_in_range(self):
        a = self._analyzer_with_mock_fred()
        result = a.analyze()
        assert -1.0 <= result.labour_score <= 1.0

    def test_regime_is_valid(self):
        a = self._analyzer_with_mock_fred()
        result = a.analyze()
        assert result.regime in ("tight", "balanced", "slack", "deteriorating")

    def test_persist_skipped_when_quits_empty(self):
        db = MagicMock()
        a = JOLTSAnalyzer(duckdb=db)
        a._client = MagicMock(spec=FredSimpleClient)
        # Only UNRATE series returns data, all JOLTS series are empty
        def side_effect(series_id, **kwargs):
            if series_id == "UNRATE":
                return _make_fred_df([4.0, 3.9, 4.1])
            return pd.DataFrame(columns=["ts", "value"])
        a._client.fetch_series.side_effect = side_effect
        result = a.analyze()
        assert isinstance(result, JOLTSSignal)
        # persist not called when quits_rate df is empty
        assert not db.execute.called


class TestComputeSignalBranches:
    def test_tight_regime_when_high_quits_and_openings(self):
        a = JOLTSAnalyzer(duckdb=None)
        # Build frames that produce high quits_rate and openings_rate
        high_df = _make_fred_df([3.0, 3.1, 3.2, 3.3], "2023-01-01")
        high_open = _make_fred_df([6.0, 6.1, 6.2, 6.3], "2023-01-01")
        low_unrate = _make_fred_df([3.5, 3.4, 3.3, 3.2], "2023-01-01")
        frames = {
            "quits_rate":    high_df,
            "openings_rate": high_open,
            "unemployment":  low_unrate,
            "hires":         high_df,
            "quits":         high_df,
            "job_openings":  high_df,
            "layoffs":       _make_fred_df([1.0, 1.0, 1.0, 1.0], "2023-01-01"),
        }
        signal = a._compute_signal(frames)
        assert signal.regime == "tight"

    def test_deteriorating_regime_on_falling_quits(self):
        a = JOLTSAnalyzer(duckdb=None)
        # Quits rate falling sharply (negative momentum)
        falling = _make_fred_df([2.5, 2.3, 2.1, 1.8], "2023-01-01")
        low_open = _make_fred_df([3.0, 2.9, 2.8, 2.7], "2023-01-01")
        unrate   = _make_fred_df([4.0, 4.2, 4.5, 4.8], "2023-01-01")
        frames = {
            "quits_rate":    falling,
            "openings_rate": low_open,
            "unemployment":  unrate,
            "hires":         falling,
            "quits":         falling,
            "job_openings":  falling,
            "layoffs":       _make_fred_df([1.5, 1.8, 2.0, 2.2], "2023-01-01"),
        }
        signal = a._compute_signal(frames)
        assert signal.regime == "deteriorating"
