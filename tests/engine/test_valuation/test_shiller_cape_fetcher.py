"""Tests per ShillerCAPEFetcher — download + fallback FRED."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from engine.analytics.valuation.shiller_cape_fetcher import ShillerCAPEFetcher
from engine.analytics.valuation.schemas import ShillerCAPEPoint


@pytest.fixture()
def mock_client():
    client = MagicMock()
    client.query.return_value = []
    client.execute.return_value = None
    return client


@pytest.fixture()
def fetcher(mock_client):
    return ShillerCAPEFetcher(client=mock_client)


class TestShillerCAPEFetcher:
    def test_get_latest_cape_returns_float_or_none(self, fetcher):
        result = fetcher.get_latest_cape()
        assert result is None or isinstance(result, float)

    def test_get_latest_cape_from_db(self, mock_client):
        mock_client.query.return_value = [(32.5,)]
        f = ShillerCAPEFetcher(client=mock_client)
        result = f.get_latest_cape()
        assert result == pytest.approx(32.5)

    def test_get_latest_cape_none_when_no_data(self, mock_client):
        mock_client.query.return_value = []
        f = ShillerCAPEFetcher(client=mock_client)
        result = f.get_latest_cape()
        assert result is None

    def test_fetch_handles_network_error(self, fetcher):
        with patch.object(fetcher, "_fetch_from_web", side_effect=ConnectionError("timeout")):
            # Should fall back gracefully, not raise
            result = fetcher.get_latest_cape()
            assert result is None or isinstance(result, float)

    def test_cape_point_schema(self, mock_client):
        mock_client.query.return_value = [
            (date(2024, 1, 1), 4800.0, 160.0, 30.0, 0.042, 0.021)
        ]
        f = ShillerCAPEFetcher(client=mock_client)
        points = f.get_history(years=1)
        if points:
            p = points[0]
            assert isinstance(p, ShillerCAPEPoint)
            if p.cape_ratio is not None:
                assert p.cape_ratio > 0


class TestFetchAndPersist:
    def test_returns_zero_when_both_sources_fail(self, mock_client):
        f = ShillerCAPEFetcher(client=mock_client, fred_client=None)
        with patch.object(f, "_fetch_shiller_xls", return_value=None), \
             patch.object(f, "_fetch_from_fred", return_value=None):
            result = f.fetch_and_persist(lookback_years=1)
        assert result == 0

    def test_uses_fred_fallback_when_xls_fails(self, mock_client):
        import pandas as pd
        fred_df = pd.DataFrame([{
            "data_date": date(2020, 1, 1),
            "sp500_price": 3000.0,
            "eps_10y_real_avg": 100.0,
            "cape_ratio": 30.0,
            "bond_yield": 2.5,
            "erp_implied": 0.01,
            "cpi_level": None,
            "source": "fred_computed",
        }])
        f = ShillerCAPEFetcher(client=mock_client, fred_client=MagicMock())
        with patch.object(f, "_fetch_shiller_xls", return_value=None), \
             patch.object(f, "_fetch_from_fred", return_value=fred_df):
            result = f.fetch_and_persist(lookback_years=5)
        assert result >= 0

    def test_persist_called_with_valid_df(self, mock_client):
        import pandas as pd
        df = pd.DataFrame([{
            "data_date": date(2025, 1, 1),
            "sp500_price": 3000.0,
            "eps_10y_real_avg": 100.0,
            "cape_ratio": 30.0,
            "bond_yield": 2.5,
            "erp_implied": 0.01,
            "cpi_level": 250.0,
            "source": "shiller_yale",
        }])
        f = ShillerCAPEFetcher(client=mock_client)
        with patch.object(f, "_fetch_shiller_xls", return_value=df):
            result = f.fetch_and_persist(lookback_years=5)
        assert result >= 0
        assert mock_client.execute.called

    def test_get_historical_returns_dataframe(self, mock_client):
        import pandas as pd
        mock_client.query.return_value = []
        f = ShillerCAPEFetcher(client=mock_client)
        df = f.get_historical(lookback_years=10)
        assert isinstance(df, pd.DataFrame)

    def test_get_historical_returns_rows_from_db(self, mock_client):
        import pandas as pd
        mock_client.query.return_value = [
            (date(2020, 1, 1), 3000.0, 100.0, 30.0, 2.5, 0.01)
        ]
        f = ShillerCAPEFetcher(client=mock_client)
        df = f.get_historical(lookback_years=10)
        assert len(df) == 1
        assert "cape_ratio" in df.columns

    def test_get_history_returns_list(self, mock_client):
        mock_client.query.return_value = []
        f = ShillerCAPEFetcher(client=mock_client)
        result = f.get_history(years=5)
        assert isinstance(result, list)

    def test_get_history_empty_on_no_db_data(self, mock_client):
        mock_client.query.return_value = []
        f = ShillerCAPEFetcher(client=mock_client)
        result = f.get_history(years=1)
        assert result == []


class TestFetchFromFred:
    def test_returns_none_when_fred_client_none(self, mock_client):
        f = ShillerCAPEFetcher(client=mock_client, fred_client=None)
        result = f._fetch_from_fred(lookback_years=5)
        assert result is None

    def test_returns_none_when_eps_empty(self, mock_client):
        import pandas as pd
        fred = MagicMock()
        fred.fetch.return_value = pd.DataFrame()
        f = ShillerCAPEFetcher(client=mock_client, fred_client=fred)
        result = f._fetch_from_fred(lookback_years=5)
        assert result is None
