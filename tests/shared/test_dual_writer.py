"""Tests for shared.db.dual_writer — the Rule 12 pipeline coordinator."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pandas as pd
import pytest

from shared.db.dual_writer import DualWriter, DualWriteResult, _NullCache
from shared.db.duckdb_client import DuckDBClient
from shared.db.duckdb_migrator import DuckDBMigrator
from shared.db.macro_repo import MacroRepository
from shared.db.prices_repo import PricesRepository
from shared.types import TimeFrame

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def dual_writer(tmp_duckdb_path: Path, tmp_path: Path) -> DualWriter:
    """DualWriter wired to fresh DuckDB + ephemeral diskcache dir."""
    client = DuckDBClient(path=tmp_duckdb_path)
    from shared.constants import MIGRATIONS_DUCKDB_DIR
    DuckDBMigrator(client=client, migrations_dir=MIGRATIONS_DUCKDB_DIR).apply_pending()
    return DualWriter(
        prices_repo=PricesRepository(client=client),
        macro_repo=MacroRepository(client=client),
        cache_dir=tmp_path / "cache",
        cache_size_mb=64,
    )


def _ohlcv_df(n: int = 5) -> pd.DataFrame:
    """Valid OHLCV DataFrame factory."""
    ts = pd.date_range(
        start=datetime(2025, 1, 1, tzinfo=UTC),
        periods=n,
        freq="D",
        tz="UTC",
    )
    return pd.DataFrame(
        {
            "ts": ts,
            "open": [100.0 + i for i in range(n)],
            "high": [101.0 + i for i in range(n)],
            "low": [99.0 + i for i in range(n)],
            "close": [100.5 + i for i in range(n)],
            "volume": [1_000 + i for i in range(n)],
        }
    )


def _macro_df(n: int = 6) -> pd.DataFrame:
    ts = pd.date_range(
        start=datetime(2024, 1, 1, tzinfo=UTC),
        periods=n,
        freq="MS",
        tz="UTC",
    )
    return pd.DataFrame({"ts": ts, "value": [1.0 * i for i in range(n)]})


class TestWritePrices:
    def test_writes_to_duckdb_and_cache(self, dual_writer: DualWriter) -> None:
        df = _ohlcv_df(5)
        result = dual_writer.write_prices(
            ticker="AAPL",
            exchange="NASDAQ",
            timeframe=TimeFrame.D1,
            df=df,
            source="test",
        )
        assert isinstance(result, DualWriteResult)
        assert result.rows_written == 5
        assert result.cached is True
        assert result.cache_key == "prices:AAPL:NASDAQ:1d"

    def test_cached_prices_readable(self, dual_writer: DualWriter) -> None:
        df = _ohlcv_df(3)
        dual_writer.write_prices("MSFT", "NASDAQ", "1d", df, source="test")

        cached = dual_writer.read_cached_prices("MSFT", "NASDAQ", "1d")
        assert cached is not None
        assert len(cached) == 3

    def test_cache_miss_returns_none(self, dual_writer: DualWriter) -> None:
        assert dual_writer.read_cached_prices("NONE", "X", "1d") is None

    def test_empty_dataframe_short_circuits(self, dual_writer: DualWriter) -> None:
        empty = pd.DataFrame(
            {
                "ts": pd.Series([], dtype="datetime64[ns, UTC]"),
                "open": pd.Series([], dtype="float64"),
                "high": pd.Series([], dtype="float64"),
                "low": pd.Series([], dtype="float64"),
                "close": pd.Series([], dtype="float64"),
                "volume": pd.Series([], dtype="int64"),
            }
        )
        result = dual_writer.write_prices("EMPTY", "X", "1d", empty, source="test")
        assert result.rows_written == 0
        assert result.cached is False

    def test_invalidate_prices_removes_from_cache(
        self, dual_writer: DualWriter
    ) -> None:
        dual_writer.write_prices("GOOG", "NASDAQ", "1d", _ohlcv_df(3), source="test")
        assert dual_writer.read_cached_prices("GOOG", "NASDAQ", "1d") is not None

        evicted = dual_writer.invalidate_prices("GOOG", "NASDAQ", "1d")
        assert evicted is True
        assert dual_writer.read_cached_prices("GOOG", "NASDAQ", "1d") is None


class TestWriteMacro:
    def test_writes_to_duckdb_and_cache(self, dual_writer: DualWriter) -> None:
        df = _macro_df(6)
        result = dual_writer.write_macro(
            "UNRATE", df, source="fred", unit="Percent", frequency="M"
        )
        assert result.rows_written == 6
        assert result.cached is True
        assert result.cache_key == "macro:UNRATE"

    def test_cached_macro_readable(self, dual_writer: DualWriter) -> None:
        dual_writer.write_macro("GDP", _macro_df(4), source="fred")
        cached = dual_writer.read_cached_macro("GDP")
        assert cached is not None
        assert len(cached) == 4

    def test_invalidate_macro(self, dual_writer: DualWriter) -> None:
        dual_writer.write_macro("CPI", _macro_df(3), source="fred")
        assert dual_writer.invalidate_macro("CPI") is True
        assert dual_writer.read_cached_macro("CPI") is None


class TestCacheKeys:
    def test_prices_key_format(self) -> None:
        key = DualWriter._build_prices_cache_key("AAPL", "NASDAQ", "1d")
        assert key == "prices:AAPL:NASDAQ:1d"

    def test_macro_key_format(self) -> None:
        key = DualWriter._build_macro_cache_key("UNRATE")
        assert key == "macro:UNRATE"


class TestNullCacheFallback:
    """Verifies the DualWriter degrades gracefully without diskcache."""

    def test_null_cache_accepts_operations_silently(self) -> None:
        cache = _NullCache()
        assert cache.set("a", "b", expire=60) is False
        assert cache.get("a") is None
        assert cache.delete("a") == 0
        cache.close()  # Non deve sollevare

    def test_dual_writer_works_with_null_cache(
        self, tmp_duckdb_path: Path
    ) -> None:
        """Forza uso del _NullCache iniettando direttamente lo stub."""
        client = DuckDBClient(path=tmp_duckdb_path)
        from shared.constants import MIGRATIONS_DUCKDB_DIR
        DuckDBMigrator(client=client, migrations_dir=MIGRATIONS_DUCKDB_DIR).apply_pending()

        dw = DualWriter(
            prices_repo=PricesRepository(client=client),
            macro_repo=MacroRepository(client=client),
        )
        # Sostituzione controllata del cache handle con NullCache
        dw._cache = _NullCache()

        result = dw.write_prices("AAA", "NYSE", "1d", _ohlcv_df(3), source="test")
        # DuckDB ha funzionato, cache no (come atteso col _NullCache)
        assert result.rows_written == 3
        assert result.cached is False
