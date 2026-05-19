"""Tests for engine.market_data.fetchers.oecd_fetcher."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import httpx
import pandas as pd
import pytest

from engine.market_data.fetchers.oecd_fetcher import OECDFetcher, OECD_SERIES, OECD_COUNTRIES
from shared.exceptions import FetchError


def _make_fetcher() -> OECDFetcher:
    with patch("httpx.Client"):
        return OECDFetcher(client=MagicMock())


def _sdmx_payload(
    periods: list[str],
    values: list[float],
    countries: list[str] | None = None,
) -> dict:
    """Minimal SDMX-JSON OECD payload."""
    countries = countries or ["USA"]
    obs = {str(i): [v] for i, v in enumerate(values)}
    series_key = ":".join(["0"] * (len(countries) + 1))
    loc_values = [{"id": c} for c in countries]
    return {
        "dataSets": [{"series": {series_key: {"observations": obs}}}],
        "structure": {
            "dimensions": {
                "observation": [
                    {"id": "TIME_PERIOD", "values": [{"id": p} for p in periods]}
                ],
                "series": [
                    {"id": "LOCATION", "values": loc_values}
                ],
            }
        },
    }


# ── Config ────────────────────────────────────────────────────────────────────

class TestConfig:
    def test_oecd_series_not_empty(self) -> None:
        assert len(OECD_SERIES) > 0

    def test_oecd_countries_not_empty(self) -> None:
        assert len(OECD_COUNTRIES) > 0


# ── fetch_series() ────────────────────────────────────────────────────────────

class TestFetchSeries:
    def test_success_returns_dataframe(self) -> None:
        fetcher = _make_fetcher()
        key = list(OECD_SERIES.keys())[0]
        payload = _sdmx_payload(["2024-01", "2024-02"], [100.5, 100.8])
        mock_resp = MagicMock()
        mock_resp.json.return_value = payload
        mock_resp.raise_for_status.return_value = None
        fetcher._http.get.return_value = mock_resp

        with patch("time.sleep"), patch.object(fetcher, "_persist"):
            df = fetcher.fetch_series(key)

        assert isinstance(df, pd.DataFrame)
        assert not df.empty

    def test_http_error_raises_fetch_error(self) -> None:
        fetcher = _make_fetcher()
        exc = httpx.HTTPStatusError("503", request=MagicMock(), response=MagicMock())
        exc.response.status_code = 503
        fetcher._http.get.side_effect = exc

        with patch("time.sleep"), pytest.raises(FetchError, match="HTTP 503"):
            fetcher.fetch_series("MEI_CLI/LOLITOAA.USA.M")

    def test_generic_exception_raises_fetch_error(self) -> None:
        fetcher = _make_fetcher()
        fetcher._http.get.side_effect = OSError("timeout")

        with patch("time.sleep"), pytest.raises(FetchError):
            fetcher.fetch_series("MEI_CLI/LOLITOAA.USA.M")

    def test_empty_datasets_returns_empty_df(self) -> None:
        fetcher = _make_fetcher()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"dataSets": [], "structure": {}}
        mock_resp.raise_for_status.return_value = None
        fetcher._http.get.return_value = mock_resp

        with patch("time.sleep"):
            df = fetcher.fetch_series("MEI_CLI/LOLITOAA.USA.M")

        assert df.empty

    def test_unknown_key_uses_custom_prefix(self) -> None:
        fetcher = _make_fetcher()
        payload = _sdmx_payload(["2024-01"], [99.5])
        mock_resp = MagicMock()
        mock_resp.json.return_value = payload
        mock_resp.raise_for_status.return_value = None
        fetcher._http.get.return_value = mock_resp

        with patch("time.sleep"), patch.object(fetcher, "_persist"):
            df = fetcher.fetch_series("CUSTOM/DATASET.USA.M")

        assert not df.empty


# ── fetch_leading_indicators() ────────────────────────────────────────────────

class TestFetchLeadingIndicators:
    def test_returns_dict(self) -> None:
        fetcher = _make_fetcher()

        def _fake(key: str, **_: object) -> pd.DataFrame:
            return pd.DataFrame([{"value": 100.5}])

        with patch.object(fetcher, "fetch_series", side_effect=_fake):
            results = fetcher.fetch_leading_indicators()

        assert len(results) == len(OECD_SERIES)

    def test_handles_errors_gracefully(self) -> None:
        fetcher = _make_fetcher()
        with patch.object(fetcher, "fetch_series", side_effect=FetchError("oecd", "err")):
            results = fetcher.fetch_leading_indicators()

        assert results == {}


# ── _parse() ─────────────────────────────────────────────────────────────────

class TestParse:
    def test_valid_monthly_periods(self) -> None:
        fetcher = _make_fetcher()
        payload = _sdmx_payload(["2024-01", "2024-02"], [100.5, 100.8])
        rows = fetcher._parse(payload, "OECD_CLI")
        assert len(rows) == 2
        assert rows[0]["value"] == 100.5

    def test_empty_datasets_returns_empty(self) -> None:
        fetcher = _make_fetcher()
        rows = fetcher._parse({"dataSets": [], "structure": {}}, "OECD_CLI")
        assert rows == []

    def test_no_time_dim_returns_empty(self) -> None:
        fetcher = _make_fetcher()
        payload = {
            "dataSets": [{"series": {"0:0": {"observations": {"0": [100.0]}}}}],
            "structure": {"dimensions": {"observation": [], "series": []}},
        }
        rows = fetcher._parse(payload, "OECD_CLI")
        assert rows == []

    def test_none_value_skipped(self) -> None:
        fetcher = _make_fetcher()
        payload = {
            "dataSets": [{"series": {"0": {"observations": {"0": [None]}}}}],
            "structure": {
                "dimensions": {
                    "observation": [{"id": "TIME_PERIOD", "values": [{"id": "2024-01"}]}],
                    "series": [],
                }
            },
        }
        rows = fetcher._parse(payload, "OECD_CLI")
        assert rows == []

    def test_out_of_bounds_idx_skipped(self) -> None:
        fetcher = _make_fetcher()
        payload = {
            "dataSets": [{"series": {"0": {"observations": {"99": [100.5]}}}}],
            "structure": {
                "dimensions": {
                    "observation": [{"id": "TIME_PERIOD", "values": [{"id": "2024-01"}]}],
                    "series": [],
                }
            },
        }
        rows = fetcher._parse(payload, "OECD_CLI")
        assert rows == []


# ── _parse_period() ───────────────────────────────────────────────────────────

class TestParsePeriod:
    def test_yyyy_mm(self) -> None:
        fetcher = _make_fetcher()
        dt = fetcher._parse_period("2024-03")
        assert dt.year == 2024
        assert dt.month == 3

    def test_yyyy_only(self) -> None:
        fetcher = _make_fetcher()
        dt = fetcher._parse_period("2024")
        assert dt.year == 2024
        assert dt.month == 1

    def test_longer_period(self) -> None:
        fetcher = _make_fetcher()
        dt = fetcher._parse_period("2024-06-15")
        assert dt.year == 2024
        assert dt.month == 6


# ── _persist() ───────────────────────────────────────────────────────────────

class TestPersist:
    def test_empty_df_skips(self) -> None:
        fetcher = _make_fetcher()
        fetcher._persist(pd.DataFrame())
        fetcher._client.execute.assert_not_called()

    def test_valid_row_persisted(self) -> None:
        fetcher = _make_fetcher()
        now = datetime.now(UTC)
        df = pd.DataFrame([{
            "series_id": "OECD_CLI_USA",
            "series_date": now,
            "value": 100.5,
            "country": "USA",
            "fetched_at": now,
        }])
        fetcher._persist(df)
        fetcher._client.execute.assert_called_once()

    def test_db_error_not_raised(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.execute.side_effect = Exception("DB error")
        now = datetime.now(UTC)
        df = pd.DataFrame([{
            "series_id": "OECD_CLI_USA", "series_date": now,
            "value": 100.5, "country": "USA", "fetched_at": now,
        }])
        fetcher._persist(df)  # should not raise
