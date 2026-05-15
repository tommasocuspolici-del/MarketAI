"""Tests PayrollFetcher — fetch FRED NFP per settore + persist payroll_sector."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest

from engine.analytics.labour_market.payroll_fetcher import PayrollFetcher, _fv


def _make_monthly_df(values: list[float], start: str = "2020-01-01") -> pd.DataFrame:
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
    # Return non-trivial data with 24 months
    fred.fetch_series.return_value = _make_monthly_df(list(range(130_000, 130_000 + 24)))
    return fred


@pytest.fixture()
def fetcher(mock_client, mock_fred):
    return PayrollFetcher(client=mock_client, fred_client=mock_fred)


class TestPayrollFetcherInit:
    def test_init_stores_dependencies(self, mock_client, mock_fred):
        f = PayrollFetcher(client=mock_client, fred_client=mock_fred)
        assert f._client is mock_client
        assert f._fred is mock_fred


class TestFetchAndPersist:
    def test_returns_int(self, fetcher):
        result = fetcher.fetch_and_persist(lookback_years=2)
        assert isinstance(result, int)
        assert result >= 0

    def test_returns_zero_when_total_nonfarm_missing(self, mock_client):
        fred = MagicMock()
        fred.fetch_series.return_value = pd.DataFrame(columns=["ts", "value"])
        f = PayrollFetcher(client=mock_client, fred_client=fred)
        result = f.fetch_and_persist(lookback_years=1)
        assert result == 0

    def test_calls_execute_for_each_sector(self, fetcher, mock_client):
        fetcher.fetch_and_persist(lookback_years=1)
        assert mock_client.execute.called

    def test_no_crash_on_fred_error(self, mock_client):
        fred = MagicMock()
        fred.fetch_series.side_effect = ConnectionError("timeout")
        f = PayrollFetcher(client=mock_client, fred_client=fred)
        result = f.fetch_and_persist(lookback_years=1)
        assert result == 0

    def test_persists_multiple_sectors(self, fetcher, mock_client):
        fetcher.fetch_and_persist(lookback_years=2)
        # With 11 sectors and 24 months, expect many execute calls
        assert mock_client.execute.call_count > 10


class TestGetLatest:
    def test_returns_dataframe(self, fetcher):
        result = fetcher.get_latest()
        assert isinstance(result, pd.DataFrame)

    def test_returns_empty_on_error(self, mock_client, mock_fred):
        mock_client.query.side_effect = Exception("DB error")
        f = PayrollFetcher(client=mock_client, fred_client=mock_fred)
        result = f.get_latest()
        assert result.empty

    def test_columns_present(self, mock_client, mock_fred):
        mock_client.query.return_value = [
            (date(2024, 1, 1), "manufacturing", 50.0, -10.0, 2.5, 8.3, True)
        ]
        f = PayrollFetcher(client=mock_client, fred_client=mock_fred)
        df = f.get_latest()
        assert "sector" in df.columns
        assert "jobs_added_k" in df.columns
        assert "is_cyclical" in df.columns

    def test_cyclical_flag_present(self, mock_client, mock_fred):
        mock_client.query.return_value = [
            (date(2024, 1, 1), "government", 10.0, 0.0, 1.0, 15.0, False)
        ]
        f = PayrollFetcher(client=mock_client, fred_client=mock_fred)
        df = f.get_latest()
        assert not df["is_cyclical"].iloc[0]


class TestHelperFunctions:
    def test_fv_returns_float_for_existing_idx(self):
        s = pd.Series([1.5, 2.5], index=pd.date_range("2020-01", periods=2, freq="MS"))
        idx = s.index[0]
        assert _fv(s, idx) == pytest.approx(1.5)

    def test_fv_returns_none_for_nan(self):
        import numpy as np
        s = pd.Series([float("nan")], index=pd.date_range("2020-01", periods=1, freq="MS"))
        assert _fv(s, s.index[0]) is None

    def test_fv_returns_none_for_missing_idx(self):
        s = pd.Series([1.0], index=pd.date_range("2020-01", periods=1, freq="MS"))
        missing = pd.Timestamp("2021-01-01")
        assert _fv(s, missing) is None
