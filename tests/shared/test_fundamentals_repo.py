"""Tests for FundamentalsRepository.

Roadmap v3.0 — Settimana 1 — coverage target ≥ 80%.

Usa DuckDB in-memory per isolare i test dal DB reale.
Schema creato inline (migration 011 replicata qui).
"""
from __future__ import annotations

from datetime import datetime, timezone

import duckdb
import numpy as np
import pandas as pd
import pytest

from shared.db.fundamentals_repo import FundamentalsRepository, reset_fundamentals_repository


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_singleton():
    """Resetta il singleton tra i test per evitare contaminazioni."""
    yield
    reset_fundamentals_repository()


@pytest.fixture
def in_memory_repo():
    """FundamentalsRepository con DuckDB in-memory + schema migration 011."""
    # Crea il client in-memory isolato
    conn = duckdb.connect(":memory:")

    # Replica lo schema della migration 011
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fundamentals_edgar (
            ticker        VARCHAR        NOT NULL,
            report_date   TIMESTAMPTZ    NOT NULL,
            period        VARCHAR        NOT NULL,
            revenue       DOUBLE,
            gross_profit  DOUBLE,
            ebit          DOUBLE,
            net_income    DOUBLE,
            eps_diluted   DOUBLE,
            total_assets  DOUBLE,
            total_debt    DOUBLE,
            equity        DOUBLE,
            fcf           DOUBLE,
            source        VARCHAR        NOT NULL DEFAULT 'edgar_xbrl',
            fetched_at    TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
            PRIMARY KEY (ticker, report_date, period)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fundamentals_valuation (
            ticker         VARCHAR        NOT NULL,
            computed_at    TIMESTAMPTZ    NOT NULL,
            pe_ttm         DOUBLE,
            pe_forward     DOUBLE,
            pb             DOUBLE,
            ps             DOUBLE,
            ev_ebitda      DOUBLE,
            dividend_yield DOUBLE,
            payout_ratio   DOUBLE,
            beta           DOUBLE,
            market_cap     DOUBLE,
            source         VARCHAR        NOT NULL DEFAULT 'alpha_vantage',
            fetched_at     TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
            PRIMARY KEY (ticker, computed_at)
        )
    """)

    # Mock del DuckDBClient che usa la connessione in-memory
    from unittest.mock import MagicMock
    from contextlib import contextmanager

    client = MagicMock()

    @contextmanager
    def _transaction():
        yield conn

    client.transaction = _transaction
    return FundamentalsRepository(client=client)


def _make_edgar_df(**overrides) -> pd.DataFrame:
    """Costruisce un DataFrame edgar con valori di test."""
    defaults = {
        "ticker": ["AAPL"],
        "report_date": [pd.Timestamp("2024-12-31", tz="UTC")],
        "period": ["FY"],
        "revenue": [391_035.0],
        "gross_profit": [169_148.0],
        "ebit": [123_216.0],
        "net_income": [93_736.0],
        "eps_diluted": [6.11],
        "total_assets": [364_840.0],
        "total_debt": [119_000.0],
        "equity": [56_950.0],
        "fcf": [108_807.0],
        "source": ["edgar_xbrl"],
    }
    defaults.update(overrides)
    return pd.DataFrame(defaults)


def _make_valuation_df(**overrides) -> pd.DataFrame:
    """Costruisce un DataFrame valuation con valori di test."""
    defaults = {
        "ticker": ["AAPL"],
        "computed_at": [pd.Timestamp.now(tz="UTC")],
        "pe_ttm": [28.5],
        "pe_forward": [25.0],
        "pb": [42.0],
        "ps": [7.5],
        "ev_ebitda": [22.0],
        "dividend_yield": [0.005],
        "payout_ratio": [0.15],
        "beta": [1.24],
        "market_cap": [2_500_000_000_000.0],
        "source": ["alpha_vantage"],
    }
    defaults.update(overrides)
    return pd.DataFrame(defaults)


# ─── Test: write_edgar ────────────────────────────────────────────────────────

class TestWriteEdgar:
    """Tests per FundamentalsRepository.write_edgar()."""

    def test_write_returns_row_count(self, in_memory_repo) -> None:
        """write_edgar restituisce il numero di righe scritte."""
        df = _make_edgar_df()
        n = in_memory_repo.write_edgar(df)
        assert n == 1

    def test_write_empty_dataframe_returns_zero(self, in_memory_repo) -> None:
        n = in_memory_repo.write_edgar(pd.DataFrame())
        assert n == 0

    def test_write_raises_if_missing_required_columns(self, in_memory_repo) -> None:
        """Mancano colonne obbligatorie → ValueError."""
        df = pd.DataFrame({"revenue": [100.0]})  # mancano ticker, report_date, period
        with pytest.raises(ValueError, match="missing required columns"):
            in_memory_repo.write_edgar(df)

    def test_write_multiple_tickers(self, in_memory_repo) -> None:
        """Batch con 2 ticker → 2 righe nel DB."""
        df = _make_edgar_df(
            ticker=["AAPL", "MSFT"],
            report_date=[
                pd.Timestamp("2024-12-31", tz="UTC"),
                pd.Timestamp("2024-12-31", tz="UTC"),
            ],
            period=["FY", "FY"],
            revenue=[391_035.0, 236_020.0],
            gross_profit=[169_148.0, 171_008.0],
            ebit=[123_216.0, 109_433.0],
            net_income=[93_736.0, 88_136.0],
            eps_diluted=[6.11, 11.45],
            total_assets=[364_840.0, 512_163.0],
            total_debt=[119_000.0, 79_975.0],
            equity=[56_950.0, 267_895.0],
            fcf=[108_807.0, 74_071.0],
            source=["edgar_xbrl", "edgar_xbrl"],
        )
        n = in_memory_repo.write_edgar(df)
        assert n == 2


# ─── Test: read_income ────────────────────────────────────────────────────────

class TestReadIncome:
    """Tests per FundamentalsRepository.read_income()."""

    def test_read_after_write(self, in_memory_repo) -> None:
        """Dato scritto → letto correttamente."""
        in_memory_repo.write_edgar(_make_edgar_df())
        df = in_memory_repo.read_income("AAPL")
        assert not df.empty
        assert df.iloc[0]["revenue"] == pytest.approx(391_035.0)

    def test_read_nonexistent_ticker_returns_empty(self, in_memory_repo) -> None:
        df = in_memory_repo.read_income("ZZZZZ_NOEXIST")
        assert df.empty

    def test_read_respects_limit(self, in_memory_repo) -> None:
        """limit=1 restituisce solo 1 riga."""
        # Scrivi 2 periodi
        df = _make_edgar_df(
            report_date=[pd.Timestamp("2024-03-31", tz="UTC")],
            period=["Q1"],
        )
        df2 = _make_edgar_df(
            report_date=[pd.Timestamp("2024-06-30", tz="UTC")],
            period=["Q2"],
        )
        in_memory_repo.write_edgar(df)
        in_memory_repo.write_edgar(df2)
        result = in_memory_repo.read_income("AAPL", limit=1)
        assert len(result) == 1

    def test_read_income_sorted_newest_first(self, in_memory_repo) -> None:
        """Righe ordinate per report_date DESC."""
        q1 = _make_edgar_df(report_date=[pd.Timestamp("2024-03-31", tz="UTC")], period=["Q1"])
        q2 = _make_edgar_df(report_date=[pd.Timestamp("2024-06-30", tz="UTC")], period=["Q2"])
        in_memory_repo.write_edgar(q1)
        in_memory_repo.write_edgar(q2)
        result = in_memory_repo.read_income("AAPL", limit=10)
        assert result.iloc[0]["period"] == "Q2"  # più recente prima


# ─── Test: write_valuation + read_valuation ───────────────────────────────────

class TestValuation:
    """Tests per write_valuation / read_valuation / read_pe_ratio."""

    def test_write_valuation_returns_count(self, in_memory_repo) -> None:
        n = in_memory_repo.write_valuation(_make_valuation_df())
        assert n == 1

    def test_write_empty_valuation_returns_zero(self, in_memory_repo) -> None:
        assert in_memory_repo.write_valuation(pd.DataFrame()) == 0

    def test_read_valuation_after_write(self, in_memory_repo) -> None:
        in_memory_repo.write_valuation(_make_valuation_df())
        df = in_memory_repo.read_valuation("AAPL")
        assert not df.empty
        assert df.iloc[0]["pe_ttm"] == pytest.approx(28.5)
        assert df.iloc[0]["beta"] == pytest.approx(1.24)

    def test_read_latest_valuation_returns_dict(self, in_memory_repo) -> None:
        in_memory_repo.write_valuation(_make_valuation_df())
        row = in_memory_repo.read_latest_valuation("AAPL")
        assert isinstance(row, dict)
        assert "pe_ttm" in row

    def test_read_latest_valuation_nonexistent_returns_none(self, in_memory_repo) -> None:
        result = in_memory_repo.read_latest_valuation("ZZZZZ")
        assert result is None

    def test_read_pe_ratio_returns_float(self, in_memory_repo) -> None:
        in_memory_repo.write_valuation(_make_valuation_df())
        pe = in_memory_repo.read_pe_ratio("AAPL")
        assert pe == pytest.approx(28.5)

    def test_read_pe_ratio_nonexistent_returns_none(self, in_memory_repo) -> None:
        assert in_memory_repo.read_pe_ratio("ZZZZZ") is None

    def test_read_pe_ratio_nan_returns_none(self, in_memory_repo) -> None:
        """P/E con NaN → None (non propagare NaN alla UI)."""
        df = _make_valuation_df(pe_ttm=[np.nan])
        in_memory_repo.write_valuation(df)
        result = in_memory_repo.read_pe_ratio("AAPL")
        assert result is None

    def test_write_raises_if_missing_required_columns(self, in_memory_repo) -> None:
        df = pd.DataFrame({"pe_ttm": [28.5]})  # mancano ticker, computed_at
        with pytest.raises(ValueError, match="missing required columns"):
            in_memory_repo.write_valuation(df)


# ─── Test: read_balance_sheet + read_latest_edgar (missing coverage) ──────────

class TestReadBalanceSheet:
    """Tests per read_balance_sheet."""

    def test_read_after_write(self, in_memory_repo) -> None:
        in_memory_repo.write_edgar(_make_edgar_df())
        df = in_memory_repo.read_balance_sheet("AAPL")
        assert not df.empty
        assert df.iloc[0]["total_assets"] == pytest.approx(364_840.0)

    def test_returns_empty_for_unknown(self, in_memory_repo) -> None:
        df = in_memory_repo.read_balance_sheet("UNKNOWN_TICKER")
        assert df.empty

    def test_respects_limit(self, in_memory_repo) -> None:
        q1 = _make_edgar_df(report_date=[pd.Timestamp("2024-03-31", tz="UTC")], period=["Q1"])
        q2 = _make_edgar_df(report_date=[pd.Timestamp("2024-06-30", tz="UTC")], period=["Q2"])
        in_memory_repo.write_edgar(q1)
        in_memory_repo.write_edgar(q2)
        result = in_memory_repo.read_balance_sheet("AAPL", limit=1)
        assert len(result) == 1


class TestReadLatestEdgar:
    """Tests per read_latest_edgar."""

    def test_returns_dict_after_write(self, in_memory_repo) -> None:
        in_memory_repo.write_edgar(_make_edgar_df())
        result = in_memory_repo.read_latest_edgar("AAPL")
        assert isinstance(result, dict)
        assert "revenue" in result

    def test_returns_none_when_no_data(self, in_memory_repo) -> None:
        result = in_memory_repo.read_latest_edgar("UNKNOWN")
        assert result is None

    def test_returns_most_recent(self, in_memory_repo) -> None:
        q1 = _make_edgar_df(report_date=[pd.Timestamp("2024-03-31", tz="UTC")], period=["Q1"])
        q2 = _make_edgar_df(report_date=[pd.Timestamp("2024-06-30", tz="UTC")], period=["Q2"])
        in_memory_repo.write_edgar(q1)
        in_memory_repo.write_edgar(q2)
        result = in_memory_repo.read_latest_edgar("AAPL")
        assert result["period"] == "Q2"


# ─── Test: error paths (DatabaseError) ────────────────────────────────────────

class TestErrorPaths:
    def test_write_edgar_database_error_propagated(self) -> None:
        from contextlib import contextmanager
        from unittest.mock import MagicMock
        from shared.exceptions import DatabaseError

        bad_client = MagicMock()

        @contextmanager
        def _bad_tx():
            conn = MagicMock()
            conn.register = MagicMock()
            conn.execute = MagicMock(side_effect=RuntimeError("DB fail"))
            yield conn

        bad_client.transaction = _bad_tx
        repo = FundamentalsRepository(client=bad_client)
        with pytest.raises(DatabaseError):
            repo.write_edgar(_make_edgar_df())

    def test_write_valuation_database_error_propagated(self) -> None:
        from contextlib import contextmanager
        from unittest.mock import MagicMock
        from shared.exceptions import DatabaseError

        bad_client = MagicMock()

        @contextmanager
        def _bad_tx():
            conn = MagicMock()
            conn.register = MagicMock()
            conn.execute = MagicMock(side_effect=RuntimeError("DB fail"))
            yield conn

        bad_client.transaction = _bad_tx
        repo = FundamentalsRepository(client=bad_client)
        with pytest.raises(DatabaseError):
            repo.write_valuation(_make_valuation_df())

    def test_read_income_db_error_returns_empty(self) -> None:
        from contextlib import contextmanager
        from unittest.mock import MagicMock

        bad_client = MagicMock()

        @contextmanager
        def _bad_tx():
            raise RuntimeError("query fail")
            yield  # noqa

        bad_client.transaction = _bad_tx
        repo = FundamentalsRepository(client=bad_client)
        df = repo.read_income("AAPL")
        assert df.empty

    def test_read_balance_sheet_db_error_returns_empty(self) -> None:
        from contextlib import contextmanager
        from unittest.mock import MagicMock

        bad_client = MagicMock()

        @contextmanager
        def _bad_tx():
            raise RuntimeError("query fail")
            yield  # noqa

        bad_client.transaction = _bad_tx
        repo = FundamentalsRepository(client=bad_client)
        df = repo.read_balance_sheet("AAPL")
        assert df.empty

    def test_read_latest_edgar_db_error_returns_none(self) -> None:
        from contextlib import contextmanager
        from unittest.mock import MagicMock

        bad_client = MagicMock()

        @contextmanager
        def _bad_tx():
            raise RuntimeError("fail")
            yield  # noqa

        bad_client.transaction = _bad_tx
        repo = FundamentalsRepository(client=bad_client)
        assert repo.read_latest_edgar("AAPL") is None

    def test_read_valuation_db_error_returns_empty(self) -> None:
        from contextlib import contextmanager
        from unittest.mock import MagicMock

        bad_client = MagicMock()

        @contextmanager
        def _bad_tx():
            raise RuntimeError("fail")
            yield  # noqa

        bad_client.transaction = _bad_tx
        repo = FundamentalsRepository(client=bad_client)
        df = repo.read_valuation("AAPL")
        assert df.empty


class TestPreparedFiltersInvalidRows:
    def test_edgar_drops_rows_with_missing_keys(self, in_memory_repo) -> None:
        df = _make_edgar_df(
            ticker=["AAPL", None],  # type: ignore[list-item]
            report_date=[pd.Timestamp("2024-12-31", tz="UTC"), pd.Timestamp("2024-12-31", tz="UTC")],
            period=["FY", "FY"],
            revenue=[100.0, 200.0],
            gross_profit=[50.0, 100.0],
            ebit=[40.0, 80.0],
            net_income=[30.0, 60.0],
            eps_diluted=[1.0, 2.0],
            total_assets=[400.0, 800.0],
            total_debt=[100.0, 200.0],
            equity=[200.0, 400.0],
            fcf=[80.0, 160.0],
            source=["edgar_xbrl", "edgar_xbrl"],
        )
        n = in_memory_repo.write_edgar(df)
        # Only 1 row written; None ticker row dropped
        assert n == 1


class TestSingleton:
    def test_get_returns_instance(self) -> None:
        from unittest.mock import patch
        from shared.db.fundamentals_repo import get_fundamentals_repository
        with patch("shared.db.fundamentals_repo.get_duckdb_client"):
            repo = get_fundamentals_repository()
            assert isinstance(repo, FundamentalsRepository)

    def test_singleton_same_instance(self) -> None:
        from unittest.mock import patch
        from shared.db.fundamentals_repo import get_fundamentals_repository
        with patch("shared.db.fundamentals_repo.get_duckdb_client"):
            r1 = get_fundamentals_repository()
            r2 = get_fundamentals_repository()
            assert r1 is r2

    def test_reset_clears_singleton(self) -> None:
        from unittest.mock import patch
        from shared.db.fundamentals_repo import (
            get_fundamentals_repository,
            reset_fundamentals_repository,
        )
        with patch("shared.db.fundamentals_repo.get_duckdb_client"):
            r1 = get_fundamentals_repository()
            reset_fundamentals_repository()
            r2 = get_fundamentals_repository()
            assert r1 is not r2
