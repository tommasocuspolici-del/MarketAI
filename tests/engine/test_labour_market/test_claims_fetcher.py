"""Tests ClaimsFetcher — fetch FRED ICSA/CCSA/IURSA + persist claims_cycle."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest

from engine.analytics.labour_market.claims_fetcher import (
    ClaimsFetcher,
    _classify_regime,
    _regime_to_signal,
)


def _make_fred_df(values: list[float], freq: str = "W-SAT") -> pd.DataFrame:
    dates = pd.date_range("2020-01-04", periods=len(values), freq=freq)
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
    fred.fetch_series.return_value = _make_fred_df([250.0] * 60)
    return fred


@pytest.fixture()
def fetcher(mock_client, mock_fred):
    return ClaimsFetcher(client=mock_client, fred_client=mock_fred)


class TestClaimsFetcherInit:
    def test_init_stores_dependencies(self, mock_client, mock_fred):
        f = ClaimsFetcher(client=mock_client, fred_client=mock_fred)
        assert f._client is mock_client
        assert f._fred is mock_fred


class TestFetchAndPersist:
    def test_returns_int(self, fetcher):
        result = fetcher.fetch_and_persist(lookback_years=1)
        assert isinstance(result, int)
        assert result >= 0

    def test_returns_zero_when_icsa_empty(self, mock_client):
        fred = MagicMock()
        fred.fetch_series.return_value = pd.DataFrame(columns=["ts", "value"])
        f = ClaimsFetcher(client=mock_client, fred_client=fred)
        result = f.fetch_and_persist(lookback_years=1)
        assert result == 0

    def test_calls_execute_on_success(self, fetcher, mock_client):
        fetcher.fetch_and_persist(lookback_years=1)
        assert mock_client.execute.called

    def test_no_crash_on_fred_error(self, mock_client):
        fred = MagicMock()
        fred.fetch_series.side_effect = RuntimeError("network")
        f = ClaimsFetcher(client=mock_client, fred_client=fred)
        result = f.fetch_and_persist(lookback_years=1)
        assert result == 0

    def test_computes_4wk_ma(self, mock_client):
        # 8 weeks at 200K → 4wk MA should equal 200K
        fred = MagicMock()
        fred.fetch_series.return_value = _make_fred_df([200.0] * 8)
        f = ClaimsFetcher(client=mock_client, fred_client=fred)
        n = f.fetch_and_persist(lookback_years=1)
        assert n >= 4  # first 3 weeks may have NA MA


class TestGetLatest:
    def test_returns_dataframe(self, fetcher):
        result = fetcher.get_latest()
        assert isinstance(result, pd.DataFrame)

    def test_returns_empty_on_db_error(self, mock_client, mock_fred):
        mock_client.query.side_effect = Exception("DB")
        f = ClaimsFetcher(client=mock_client, fred_client=mock_fred)
        result = f.get_latest()
        assert result.empty

    def test_returns_data_from_db(self, mock_client, mock_fred):
        mock_client.query.return_value = [
            (date(2024, 1, 6), 210_000, 1_800_000, 1.2, 215_000.0, -5.0, 2.0,
             "expansion", 0.7)
        ]
        f = ClaimsFetcher(client=mock_client, fred_client=mock_fred)
        df = f.get_latest()
        assert len(df) == 1
        assert df["cycle_regime"].iloc[0] == "expansion"


class TestClassifyRegime:
    def test_expansion_low_claims(self):
        assert _classify_regime(250_000, 5.0) == "expansion"

    def test_peak_mid_claims(self):
        assert _classify_regime(325_000, 15.0) == "peak"

    def test_contraction_high_claims(self):
        assert _classify_regime(450_000, 30.0) == "contraction"

    def test_none_ma_returns_unknown(self):
        assert _classify_regime(None, 0.0) == "unknown"


class TestRegimeToSignal:
    def test_expansion_positive(self):
        assert _regime_to_signal("expansion") > 0

    def test_contraction_negative(self):
        assert _regime_to_signal("contraction") < 0

    def test_unknown_regime_none(self):
        assert _regime_to_signal("nonexistent") is None

    def test_peak_near_zero(self):
        sig = _regime_to_signal("peak")
        assert sig is not None
        assert -0.5 < sig < 0.5
