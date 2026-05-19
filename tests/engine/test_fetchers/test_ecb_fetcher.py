"""Tests for engine.market_data.fetchers.ecb_fetcher."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import httpx
import pandas as pd
import pytest

from engine.market_data.fetchers.ecb_fetcher import ECBFetcher, ECB_SERIES
from shared.exceptions import FetchError


def _make_fetcher() -> ECBFetcher:
    with patch("httpx.Client"):
        return ECBFetcher(client=MagicMock())


def _sdmx_payload(periods: list[str], values: list[float]) -> dict:
    """Minimal valid SDMX-JSON response from ECB."""
    obs = {str(i): [v] for i, v in enumerate(values)}
    return {
        "dataSets": [{"series": {"0:0:0:0:0": {"observations": obs}}}],
        "structure": {
            "dimensions": {
                "observation": [
                    {
                        "id": "TIME_PERIOD",
                        "values": [{"id": p} for p in periods],
                    }
                ]
            }
        },
    }


# ── Constructor / config ──────────────────────────────────────────────────────

class TestInit:
    def test_ecb_series_not_empty(self) -> None:
        assert len(ECB_SERIES) > 0

    def test_fetcher_created(self) -> None:
        assert _make_fetcher() is not None


# ── fetch_series() ────────────────────────────────────────────────────────────

class TestFetchSeries:
    def test_success_returns_dataframe(self) -> None:
        fetcher = _make_fetcher()
        payload = _sdmx_payload(["2024-01", "2024-02"], [4.0, 4.25])
        mock_resp = MagicMock()
        mock_resp.json.return_value = payload
        mock_resp.raise_for_status.return_value = None
        fetcher._http.get.return_value = mock_resp

        with patch("time.sleep"), patch.object(fetcher, "_persist"):
            df = fetcher.fetch_series("FM/B.U2.EUR.4F.KR.MRR_FR.LEV")

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert "series_id" in df.columns
        assert "value" in df.columns

    def test_http_error_raises_fetch_error(self) -> None:
        fetcher = _make_fetcher()
        exc = httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock())
        exc.response.status_code = 404
        fetcher._http.get.side_effect = exc

        with patch("time.sleep"), pytest.raises(FetchError, match="HTTP 404"):
            fetcher.fetch_series("FM/B.U2.EUR.4F.KR.MRR_FR.LEV")

    def test_generic_exception_raises_fetch_error(self) -> None:
        fetcher = _make_fetcher()
        fetcher._http.get.side_effect = OSError("timeout")

        with patch("time.sleep"), pytest.raises(FetchError):
            fetcher.fetch_series("FM/B.U2.EUR.4F.KR.MRR_FR.LEV")

    def test_empty_response_returns_empty_df(self) -> None:
        fetcher = _make_fetcher()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"dataSets": [], "structure": {}}
        mock_resp.raise_for_status.return_value = None
        fetcher._http.get.return_value = mock_resp

        with patch("time.sleep"):
            df = fetcher.fetch_series("FM/B.U2.EUR.4F.KR.MRR_FR.LEV")

        assert df.empty

    def test_unknown_series_key_still_works(self) -> None:
        fetcher = _make_fetcher()
        payload = _sdmx_payload(["2024-01"], [1.5])
        mock_resp = MagicMock()
        mock_resp.json.return_value = payload
        mock_resp.raise_for_status.return_value = None
        fetcher._http.get.return_value = mock_resp

        with patch("time.sleep"), patch.object(fetcher, "_persist"):
            df = fetcher.fetch_series("CUSTOM/SERIES.KEY")

        assert not df.empty


# ── fetch_all() ───────────────────────────────────────────────────────────────

class TestFetchAll:
    def test_fetch_all_returns_dict(self) -> None:
        fetcher = _make_fetcher()

        def _fake_fetch(series_key: str, **_: object) -> pd.DataFrame:
            return pd.DataFrame([{"series_id": "X", "value": 1.0}])

        with patch.object(fetcher, "fetch_series", side_effect=_fake_fetch):
            results = fetcher.fetch_all()

        assert len(results) == len(ECB_SERIES)

    def test_fetch_all_handles_errors_gracefully(self) -> None:
        fetcher = _make_fetcher()

        with patch.object(fetcher, "fetch_series", side_effect=FetchError("ecb", "error")):
            results = fetcher.fetch_all()

        assert results == {}


# ── _parse_json() ─────────────────────────────────────────────────────────────

class TestParseJson:
    def test_valid_monthly_periods(self) -> None:
        fetcher = _make_fetcher()
        payload = _sdmx_payload(["2024-01", "2024-02"], [4.0, 4.25])
        rows = fetcher._parse_json(payload, "ECB_MRR")
        assert len(rows) == 2
        assert rows[0]["value"] == 4.0
        assert rows[0]["series_id"] == "ECB_MRR"

    def test_empty_datasets_returns_empty(self) -> None:
        fetcher = _make_fetcher()
        rows = fetcher._parse_json({"dataSets": [], "structure": {}}, "ECB_MRR")
        assert rows == []

    def test_no_time_dim_returns_empty(self) -> None:
        fetcher = _make_fetcher()
        payload = {
            "dataSets": [{"series": {"0:0": {"observations": {"0": [4.0]}}}}],
            "structure": {"dimensions": {"observation": [{"id": "OTHER_DIM", "values": []}]}},
        }
        rows = fetcher._parse_json(payload, "ECB_MRR")
        assert rows == []

    def test_none_observation_value_skipped(self) -> None:
        fetcher = _make_fetcher()
        payload = {
            "dataSets": [{"series": {"0:0": {"observations": {"0": [None]}}}}],
            "structure": {
                "dimensions": {
                    "observation": [{"id": "TIME_PERIOD", "values": [{"id": "2024-01"}]}]
                }
            },
        }
        rows = fetcher._parse_json(payload, "ECB_MRR")
        assert rows == []

    def test_out_of_bounds_idx_skipped(self) -> None:
        fetcher = _make_fetcher()
        payload = {
            "dataSets": [{"series": {"0:0": {"observations": {"99": [4.0]}}}}],
            "structure": {
                "dimensions": {
                    "observation": [{"id": "TIME_PERIOD", "values": [{"id": "2024-01"}]}]
                }
            },
        }
        rows = fetcher._parse_json(payload, "ECB_MRR")
        assert rows == []


# ── _parse_period() ───────────────────────────────────────────────────────────

class TestParsePeriod:
    def test_yyyy_mm(self) -> None:
        fetcher = _make_fetcher()
        dt = fetcher._parse_period("2024-03")
        assert dt.year == 2024
        assert dt.month == 3
        assert dt.day == 1

    def test_yyyy_mm_dd(self) -> None:
        fetcher = _make_fetcher()
        dt = fetcher._parse_period("2024-03-15")
        assert dt.year == 2024
        assert dt.month == 3
        assert dt.day == 15

    def test_yyyy_only(self) -> None:
        fetcher = _make_fetcher()
        dt = fetcher._parse_period("2024")
        assert dt.year == 2024


# ── _persist() ───────────────────────────────────────────────────────────────

class TestPersist:
    def test_empty_df_skips(self) -> None:
        fetcher = _make_fetcher()
        fetcher._persist(pd.DataFrame())
        fetcher._client.execute.assert_not_called()

    def test_rows_persisted(self) -> None:
        fetcher = _make_fetcher()
        now = datetime.now(UTC)
        df = pd.DataFrame([{
            "series_id": "ECB_MRR",
            "series_date": now,
            "value": 4.0,
            "fetched_at": now,
        }])
        fetcher._persist(df)
        fetcher._client.execute.assert_called_once()

    def test_db_error_logged_not_raised(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.execute.side_effect = Exception("DB error")
        now = datetime.now(UTC)
        df = pd.DataFrame([{
            "series_id": "ECB_MRR", "series_date": now, "value": 4.0, "fetched_at": now,
        }])
        fetcher._persist(df)  # should not raise
