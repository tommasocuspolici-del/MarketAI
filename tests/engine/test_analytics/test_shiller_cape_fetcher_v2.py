"""Tests per engine.analytics.valuation.shiller_cape_fetcher — ShillerCAPEFetcher.
Extended coverage for _fetch_shiller_xls, _fetch_from_fred, _persist, get_latest_cape.
"""
from __future__ import annotations

import io
from contextlib import contextmanager
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import duckdb
import numpy as np
import pandas as pd
import pytest

from engine.analytics.valuation.shiller_cape_fetcher import ShillerCAPEFetcher


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS shiller_cape_historical (
    data_date        DATE PRIMARY KEY,
    sp500_price      DOUBLE,
    eps_10y_real_avg DOUBLE,
    cape_ratio       DOUBLE,
    bond_yield       DOUBLE,
    erp_implied      DOUBLE,
    cpi_level        DOUBLE,
    source           VARCHAR,
    fetched_at       TIMESTAMPTZ DEFAULT NOW()
)
"""


def _make_client():
    conn = duckdb.connect(":memory:")
    conn.execute(_CREATE_TABLE)
    client = MagicMock()
    client.execute = conn.execute
    client.query = lambda sql, p=None: conn.execute(sql, p or []).fetchall()
    return client, conn


def _make_fetcher(client=None):
    if client is None:
        client, _ = _make_client()
    return ShillerCAPEFetcher(client=client)


class TestPersist:
    def test_persist_empty_df_returns_0(self) -> None:
        fetcher = _make_fetcher()
        assert fetcher._persist(pd.DataFrame()) == 0

    def test_persist_rows(self) -> None:
        client, conn = _make_client()
        fetcher = ShillerCAPEFetcher(client=client)
        df = pd.DataFrame([{
            "data_date": date(2024, 1, 1),
            "sp500_price": 4800.0,
            "eps_10y_real_avg": 120.0,
            "cape_ratio": 30.5,
            "bond_yield": 4.1,
            "erp_implied": -0.8,
            "cpi_level": 310.0,
            "source": "test",
        }])
        n = fetcher._persist(df)
        assert n == 1
        rows = conn.execute("SELECT COUNT(*) FROM shiller_cape_historical").fetchone()[0]
        assert rows == 1

    def test_persist_skips_row_with_none_date(self) -> None:
        client, conn = _make_client()
        fetcher = ShillerCAPEFetcher(client=client)
        df = pd.DataFrame([{
            "data_date": None,
            "sp500_price": 4800.0,
            "cape_ratio": 30.5,
            "source": "test",
        }])
        n = fetcher._persist(df)
        assert n == 0

    def test_persist_handles_db_error_gracefully(self) -> None:
        client = MagicMock()
        client.execute = MagicMock(side_effect=RuntimeError("DB fail"))
        fetcher = ShillerCAPEFetcher(client=client)
        df = pd.DataFrame([{
            "data_date": date(2024, 1, 1),
            "sp500_price": 4800.0,
            "cape_ratio": 30.5,
            "source": "test",
        }])
        n = fetcher._persist(df)
        assert n == 0

    def test_persist_upsert_on_conflict(self) -> None:
        client, conn = _make_client()
        fetcher = ShillerCAPEFetcher(client=client)
        row = {
            "data_date": date(2024, 1, 1),
            "sp500_price": 4800.0,
            "eps_10y_real_avg": None,
            "cape_ratio": 30.5,
            "bond_yield": None,
            "erp_implied": None,
            "cpi_level": None,
            "source": "test",
        }
        fetcher._persist(pd.DataFrame([row]))
        # Update
        row["cape_ratio"] = 31.0
        fetcher._persist(pd.DataFrame([row]))
        rows = conn.execute("SELECT cape_ratio FROM shiller_cape_historical").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == pytest.approx(31.0)


class TestGetLatestCape:
    def test_returns_none_when_empty(self) -> None:
        fetcher = _make_fetcher()
        assert fetcher.get_latest_cape() is None

    def test_returns_float_when_data_present(self) -> None:
        client, conn = _make_client()
        conn.execute(
            "INSERT INTO shiller_cape_historical (data_date, cape_ratio, source) "
            "VALUES ('2024-01-01', 28.5, 'test')"
        )
        fetcher = ShillerCAPEFetcher(client=client)
        val = fetcher.get_latest_cape()
        assert val == pytest.approx(28.5)

    def test_returns_most_recent(self) -> None:
        client, conn = _make_client()
        conn.execute(
            "INSERT INTO shiller_cape_historical (data_date, cape_ratio, source) "
            "VALUES ('2024-01-01', 28.5, 'test'), ('2024-06-01', 32.1, 'test')"
        )
        fetcher = ShillerCAPEFetcher(client=client)
        val = fetcher.get_latest_cape()
        assert val == pytest.approx(32.1)

    def test_returns_none_on_db_error(self) -> None:
        client = MagicMock()
        client.query = MagicMock(side_effect=RuntimeError("fail"))
        fetcher = ShillerCAPEFetcher(client=client)
        assert fetcher.get_latest_cape() is None


class TestGetHistory:
    def test_returns_empty_list_when_no_data(self) -> None:
        fetcher = _make_fetcher()
        assert fetcher.get_history(years=5) == []

    def test_returns_shiller_cape_points(self) -> None:
        client, conn = _make_client()
        for y in range(2020, 2024):
            conn.execute(
                f"INSERT INTO shiller_cape_historical (data_date, sp500_price, cape_ratio, source) "
                f"VALUES ('{y}-01-01', {4000 + y}, {25.0 + y}, 'test')"
            )
        fetcher = ShillerCAPEFetcher(client=client)
        pts = fetcher.get_history(years=10)
        assert len(pts) == 4


class TestFetchShillerXls:
    def _make_fake_xls_bytes(self) -> bytes:
        """Creates a minimal Excel that mimics the Shiller data format."""
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Data"
        # Skip 7 rows (header), then data
        for i in range(7):
            ws.append([""] * 12)
        # Header row (row 8)
        ws.append(["Date", "P", "D", "E", "CPI", "Frac", "RP", "RD", "RE", "CAPE", "TR", "RI"])
        # Two data rows
        ws.append([1881.01, 5.58, 0.18, 0.40, None, None, None, None, None, None, None, None])
        ws.append([1881.02, 5.52, 0.18, 0.40, 9.5, None, None, None, None, 16.5, None, None])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_fetch_and_persist_uses_fred_on_failure(self) -> None:
        """When _fetch_shiller_xls returns None, falls back to _fetch_from_fred."""
        fetcher = _make_fetcher()
        with patch.object(fetcher, "_fetch_shiller_xls", return_value=None):
            with patch.object(fetcher, "_fetch_from_fred", return_value=None):
                n = fetcher.fetch_and_persist(lookback_years=5)
        assert n == 0

    def test_fetch_and_persist_with_mocked_xls(self) -> None:
        """fetch_and_persist succeeds when _fetch_shiller_xls returns valid data."""
        client, conn = _make_client()
        fetcher = ShillerCAPEFetcher(client=client)
        today = date.today()
        recent_data = pd.DataFrame([{
            "data_date": today - timedelta(days=30),
            "sp500_price": 5000.0,
            "eps_10y_real_avg": 150.0,
            "cape_ratio": 33.0,
            "bond_yield": None,
            "erp_implied": None,
            "cpi_level": 315.0,
            "source": "shiller_yale",
        }])
        with patch.object(fetcher, "_fetch_shiller_xls", return_value=recent_data):
            n = fetcher.fetch_and_persist(lookback_years=5)
        assert n == 1


class TestFetchFromFred:
    def test_returns_none_when_no_fred_client(self) -> None:
        fetcher = _make_fetcher()
        assert fetcher._fred is None
        result = fetcher._fetch_from_fred(lookback_years=5)
        assert result is None

    def test_returns_none_when_eps_empty(self) -> None:
        mock_fred = MagicMock()
        mock_fred.fetch_series = MagicMock(return_value=None)
        client, _ = _make_client()
        fetcher = ShillerCAPEFetcher(client=client, fred_client=mock_fred)
        result = fetcher._fetch_from_fred(lookback_years=5)
        assert result is None

    def test_builds_dataframe_from_fred_data(self) -> None:
        mock_fred = MagicMock()
        # Create plausible time-series data
        idx = pd.date_range("2015-01-01", periods=120, freq="ME", tz="UTC")
        eps_df = pd.DataFrame({"value": np.linspace(100, 160, 120)}, index=idx)
        sp500_df = pd.DataFrame({"value": np.linspace(2000, 5000, 120)}, index=idx)
        cpi_df = pd.DataFrame({"value": np.linspace(240, 310, 120)}, index=idx)
        dgs10_df = pd.DataFrame({"value": np.linspace(1.5, 4.5, 120)}, index=idx)

        mock_fred.fetch_series = MagicMock(
            side_effect=[eps_df, cpi_df, dgs10_df, sp500_df]
        )
        client, _ = _make_client()
        fetcher = ShillerCAPEFetcher(client=client, fred_client=mock_fred)
        result = fetcher._fetch_from_fred(lookback_years=5)
        assert result is not None
        assert len(result) > 0
        assert "cape_ratio" in result.columns
        assert "source" in result.columns
        assert (result["source"] == "fred_computed").all()
