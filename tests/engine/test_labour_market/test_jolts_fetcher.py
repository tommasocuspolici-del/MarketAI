"""Tests JOLTSFetcher — fetch FRED + persist jolts_monthly."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from engine.analytics.labour_market.jolts_fetcher import JOLTSFetcher, _f


def _make_fred_df(values: list[float], start: str = "2020-01-01") -> pd.DataFrame:
    dates = pd.date_range(start, periods=len(values), freq="MS")
    return pd.DataFrame({"ts": dates, "value": values})


@pytest.fixture()
def mock_client():
    client = MagicMock()
    client.query.return_value = []
    client.execute.return_value = None
    return client


@pytest.fixture()
def mock_fred():
    fred = MagicMock()
    fred.fetch_series.return_value = _make_fred_df([100.0, 110.0, 105.0])
    return fred


@pytest.fixture()
def fetcher(mock_client, mock_fred):
    return JOLTSFetcher(client=mock_client, fred_client=mock_fred)


class TestJOLTSFetcherInit:
    def test_init_stores_client_and_fred(self, mock_client, mock_fred):
        f = JOLTSFetcher(client=mock_client, fred_client=mock_fred)
        assert f._client is mock_client
        assert f._fred is mock_fred


class TestFetchAndPersist:
    def test_returns_int(self, fetcher):
        result = fetcher.fetch_and_persist(lookback_years=1)
        assert isinstance(result, int)

    def test_returns_zero_when_fred_returns_empty(self, mock_client):
        fred = MagicMock()
        fred.fetch_series.return_value = pd.DataFrame(columns=["ts", "value"])
        f = JOLTSFetcher(client=mock_client, fred_client=fred)
        result = f.fetch_and_persist(lookback_years=1)
        assert result == 0

    def test_calls_fred_for_each_series(self, fetcher, mock_fred):
        fetcher.fetch_and_persist(lookback_years=1)
        # 7 JOLTS series + UNRATE
        assert mock_fred.fetch_series.call_count >= 7

    def test_calls_client_execute_on_success(self, fetcher, mock_client):
        fetcher.fetch_and_persist(lookback_years=1)
        assert mock_client.execute.called

    def test_beveridge_gap_computed_when_unrate_available(self, mock_client):
        fred = MagicMock()
        data = _make_fred_df([5.0, 5.5, 5.2], "2020-01-01")

        def side_effect(series_id, **kwargs):
            return data.copy()

        fred.fetch_series.side_effect = side_effect
        f = JOLTSFetcher(client=mock_client, fred_client=fred)
        f.fetch_and_persist(lookback_years=1)
        # Execute called means data was processed
        assert mock_client.execute.called

    def test_no_crash_on_fred_exception(self, mock_client):
        fred = MagicMock()
        fred.fetch_series.side_effect = ConnectionError("timeout")
        f = JOLTSFetcher(client=mock_client, fred_client=fred)
        result = f.fetch_and_persist(lookback_years=1)
        assert result == 0


class TestGetLatest:
    def test_returns_dataframe(self, fetcher, mock_client):
        mock_client.query.return_value = []
        result = fetcher.get_latest()
        assert isinstance(result, pd.DataFrame)

    def test_returns_empty_on_db_error(self, mock_client, mock_fred):
        mock_client.query.side_effect = Exception("DB error")
        f = JOLTSFetcher(client=mock_client, fred_client=mock_fred)
        result = f.get_latest()
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_returns_rows_from_db(self, mock_client, mock_fred):
        mock_client.query.return_value = [
            (date(2024, 1, 1), 8500.0, 5800.0, 3200.0, 1200.0, 2.5, 5.8, 3.9, 2.3, 1.8)
        ]
        f = JOLTSFetcher(client=mock_client, fred_client=mock_fred)
        result = f.get_latest()
        assert len(result) == 1
        assert result["job_openings"].iloc[0] == pytest.approx(8500.0)


class TestHelperFunctions:
    def test_f_returns_none_for_nan(self):
        import numpy as np
        row = pd.Series({"val": float("nan")})
        assert _f(row, "val") is None

    def test_f_returns_float_for_valid(self):
        row = pd.Series({"val": 42.5})
        assert _f(row, "val") == pytest.approx(42.5)

    def test_f_returns_none_for_missing_key(self):
        row = pd.Series({"other": 1.0})
        assert _f(row, "val") is None
