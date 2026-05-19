"""Tests for engine.market_data.fetchers.imf_fetcher."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import httpx
import pandas as pd
import pytest

from engine.market_data.fetchers.imf_fetcher import IMFFetcher, IMF_SERIES, IMF_COUNTRIES
from shared.exceptions import FetchError


def _make_fetcher() -> IMFFetcher:
    with patch("httpx.Client"):
        return IMFFetcher(client=MagicMock())


def _imf_payload(indicator: str, countries: list[str], years: list[int]) -> dict:
    """Minimal valid IMF DataMapper API response."""
    values: dict = {}
    country_data: dict = {}
    for c in countries:
        country_data[c] = {str(y): 2.5 for y in years}
    values[indicator] = country_data
    return {"values": values}


# ── Config ────────────────────────────────────────────────────────────────────

class TestConfig:
    def test_imf_series_not_empty(self) -> None:
        assert len(IMF_SERIES) > 0

    def test_imf_countries_not_empty(self) -> None:
        assert len(IMF_COUNTRIES) > 0


# ── fetch_series() ────────────────────────────────────────────────────────────

class TestFetchSeries:
    def test_success_returns_dataframe(self) -> None:
        fetcher = _make_fetcher()
        payload = _imf_payload("NGDP_RPCH", ["USA", "DEU"], [2022, 2023])
        mock_resp = MagicMock()
        mock_resp.json.return_value = payload
        mock_resp.raise_for_status.return_value = None
        fetcher._http.get.return_value = mock_resp

        with patch("time.sleep"), patch.object(fetcher, "_persist"):
            df = fetcher.fetch_series("NGDP_RPCH", countries=["USA", "DEU"], start_year=2022)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 4  # 2 countries x 2 years
        assert "country" in df.columns
        assert "value" in df.columns

    def test_http_error_raises_fetch_error(self) -> None:
        fetcher = _make_fetcher()
        exc = httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock())
        exc.response.status_code = 404
        fetcher._http.get.side_effect = exc

        with patch("time.sleep"), pytest.raises(FetchError, match="HTTP 404"):
            fetcher.fetch_series("NGDP_RPCH")

    def test_generic_exception_raises_fetch_error(self) -> None:
        fetcher = _make_fetcher()
        fetcher._http.get.side_effect = OSError("timeout")

        with patch("time.sleep"), pytest.raises(FetchError):
            fetcher.fetch_series("NGDP_RPCH")

    def test_empty_values_returns_empty_df(self) -> None:
        fetcher = _make_fetcher()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"values": {"NGDP_RPCH": {}}}
        mock_resp.raise_for_status.return_value = None
        fetcher._http.get.return_value = mock_resp

        with patch("time.sleep"):
            df = fetcher.fetch_series("NGDP_RPCH", countries=["USA"])

        assert df.empty

    def test_uses_default_countries_when_none(self) -> None:
        fetcher = _make_fetcher()
        payload = _imf_payload("NGDP_RPCH", IMF_COUNTRIES[:2], [2023])
        mock_resp = MagicMock()
        mock_resp.json.return_value = payload
        mock_resp.raise_for_status.return_value = None
        fetcher._http.get.return_value = mock_resp

        with patch("time.sleep"), patch.object(fetcher, "_persist"):
            df = fetcher.fetch_series("NGDP_RPCH", countries=None)

        assert not df.empty

    def test_years_before_start_year_filtered(self) -> None:
        fetcher = _make_fetcher()
        payload = _imf_payload("NGDP_RPCH", ["USA"], [2005, 2010, 2023])
        mock_resp = MagicMock()
        mock_resp.json.return_value = payload
        mock_resp.raise_for_status.return_value = None
        fetcher._http.get.return_value = mock_resp

        with patch("time.sleep"), patch.object(fetcher, "_persist"):
            df = fetcher.fetch_series("NGDP_RPCH", countries=["USA"], start_year=2010)

        assert all(df["year"] >= 2010)

    def test_none_value_included_as_none(self) -> None:
        fetcher = _make_fetcher()
        payload = {"values": {"NGDP_RPCH": {"USA": {"2023": None}}}}
        mock_resp = MagicMock()
        mock_resp.json.return_value = payload
        mock_resp.raise_for_status.return_value = None
        fetcher._http.get.return_value = mock_resp

        with patch("time.sleep"), patch.object(fetcher, "_persist"):
            df = fetcher.fetch_series("NGDP_RPCH", countries=["USA"], start_year=2023)

        assert len(df) == 1
        assert df.iloc[0]["value"] is None

    def test_country_not_in_requested_list_filtered(self) -> None:
        fetcher = _make_fetcher()
        payload = {"values": {"NGDP_RPCH": {"CAN": {"2023": 1.5}, "USA": {"2023": 2.5}}}}
        mock_resp = MagicMock()
        mock_resp.json.return_value = payload
        mock_resp.raise_for_status.return_value = None
        fetcher._http.get.return_value = mock_resp

        with patch("time.sleep"), patch.object(fetcher, "_persist"):
            df = fetcher.fetch_series("NGDP_RPCH", countries=["USA"], start_year=2023)

        assert len(df) == 1
        assert df.iloc[0]["country"] == "USA"


# ── fetch_all_key_series() ────────────────────────────────────────────────────

class TestFetchAllKeySeries:
    def test_returns_dict_with_results(self) -> None:
        fetcher = _make_fetcher()

        def _fake(indicator: str, **_: object) -> pd.DataFrame:
            return pd.DataFrame([{"country": "USA", "value": 2.5}])

        with patch.object(fetcher, "fetch_series", side_effect=_fake):
            results = fetcher.fetch_all_key_series()

        assert len(results) == len(IMF_SERIES)

    def test_handles_errors_gracefully(self) -> None:
        fetcher = _make_fetcher()
        with patch.object(fetcher, "fetch_series", side_effect=FetchError("imf", "error")):
            results = fetcher.fetch_all_key_series()

        assert results == {}


# ── _persist() ───────────────────────────────────────────────────────────────

class TestPersist:
    def test_empty_df_skips(self) -> None:
        fetcher = _make_fetcher()
        fetcher._persist(pd.DataFrame())
        fetcher._client.execute.assert_not_called()

    def test_none_value_row_skipped(self) -> None:
        fetcher = _make_fetcher()
        df = pd.DataFrame([{
            "series_id": "IMF_NGDP_RPCH_USA",
            "year": 2023,
            "value": None,
            "fetched_at": datetime.now(UTC),
        }])
        fetcher._persist(df)
        fetcher._client.execute.assert_not_called()

    def test_valid_row_persisted(self) -> None:
        fetcher = _make_fetcher()
        df = pd.DataFrame([{
            "series_id": "IMF_NGDP_RPCH_USA",
            "year": 2023,
            "value": 2.5,
            "fetched_at": datetime.now(UTC),
        }])
        fetcher._persist(df)
        fetcher._client.execute.assert_called_once()

    def test_db_error_not_raised(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.execute.side_effect = Exception("DB error")
        df = pd.DataFrame([{
            "series_id": "IMF_NGDP_RPCH_USA",
            "year": 2023,
            "value": 2.5,
            "fetched_at": datetime.now(UTC),
        }])
        fetcher._persist(df)  # should not raise
