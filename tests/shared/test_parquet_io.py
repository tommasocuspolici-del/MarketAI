"""Tests for shared.db.parquet_io."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pandas as pd
import pytest

from shared.db.duckdb_client import DuckDBClient
from shared.db.duckdb_migrator import DuckDBMigrator
from shared.db.parquet_io import ParquetIO
from shared.db.prices_repo import PricesRepository
from shared.exceptions import DuckDBError
from shared.types import TimeFrame

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def migrated_client(tmp_duckdb_path: Path) -> DuckDBClient:
    client = DuckDBClient(path=tmp_duckdb_path)
    from shared.constants import MIGRATIONS_DUCKDB_DIR
    DuckDBMigrator(client=client, migrations_dir=MIGRATIONS_DUCKDB_DIR).apply_pending()
    return client


def _populate_prices(client: DuckDBClient, n_bars: int = 10) -> None:
    """Helper: insert OHLCV rows via the repository."""
    repo = PricesRepository(client=client)
    ts = pd.date_range(
        start=datetime(2025, 1, 1, tzinfo=UTC), periods=n_bars, freq="D", tz="UTC"
    )
    df = pd.DataFrame(
        {
            "ts": ts,
            "open": [100.0 + i for i in range(n_bars)],
            "high": [101.0 + i for i in range(n_bars)],
            "low": [99.0 + i for i in range(n_bars)],
            "close": [100.5 + i for i in range(n_bars)],
            "volume": [1_000_000 + i for i in range(n_bars)],
        }
    )
    repo.write_ohlcv("AAPL", "NASDAQ", TimeFrame.D1, df, source="test")


class TestExportTable:
    def test_export_creates_parquet_file(
        self, migrated_client: DuckDBClient, tmp_path: Path
    ) -> None:
        _populate_prices(migrated_client, n_bars=10)
        io = ParquetIO(client=migrated_client)

        output = tmp_path / "prices.parquet"
        result = io.export_table("prices_ohlcv", output)

        assert result == output
        assert output.exists()
        assert output.stat().st_size > 0

    def test_export_file_is_readable_parquet(
        self, migrated_client: DuckDBClient, tmp_path: Path
    ) -> None:
        _populate_prices(migrated_client, n_bars=15)
        io = ParquetIO(client=migrated_client)
        output = tmp_path / "prices.parquet"
        io.export_table("prices_ohlcv", output)

        # Verifica: leggibile con pandas + ha le righe attese
        df = pd.read_parquet(output)
        assert len(df) == 15
        assert "ticker" in df.columns
        assert "close" in df.columns

    def test_export_nonexistent_table_raises(
        self, migrated_client: DuckDBClient, tmp_path: Path
    ) -> None:
        io = ParquetIO(client=migrated_client)
        with pytest.raises(DuckDBError, match="does not exist"):
            io.export_table("ghost_table", tmp_path / "x.parquet")

    def test_export_query(
        self, migrated_client: DuckDBClient, tmp_path: Path
    ) -> None:
        _populate_prices(migrated_client, n_bars=20)
        io = ParquetIO(client=migrated_client)
        output = tmp_path / "subset.parquet"
        io.export_query(
            "SELECT ticker, ts, close FROM prices_ohlcv WHERE close > 105",
            output,
        )

        df = pd.read_parquet(output)
        assert len(df) > 0
        assert set(df.columns) == {"ticker", "ts", "close"}
        assert (df["close"] > 105).all()


class TestImportTable:
    def test_roundtrip_export_import(
        self, migrated_client: DuckDBClient, tmp_path: Path, tmp_duckdb_path: Path
    ) -> None:
        _populate_prices(migrated_client, n_bars=10)
        io = ParquetIO(client=migrated_client)

        # Export
        archive = tmp_path / "backup.parquet"
        io.export_table("prices_ohlcv", archive)
        migrated_client.close()

        # Nuovo database, ripristina da Parquet
        fresh_db = tmp_path / "fresh.duckdb"
        fresh_client = DuckDBClient(path=fresh_db)
        from shared.constants import MIGRATIONS_DUCKDB_DIR
        DuckDBMigrator(client=fresh_client, migrations_dir=MIGRATIONS_DUCKDB_DIR).apply_pending()

        fresh_io = ParquetIO(client=fresh_client)
        n = fresh_io.import_table("prices_ohlcv", archive, mode="append")

        assert n == 10
        rows = fresh_client.query("SELECT COUNT(*) FROM prices_ohlcv")
        assert rows[0][0] == 10
        fresh_client.close()

    def test_import_upsert_mode_idempotent(
        self, migrated_client: DuckDBClient, tmp_path: Path
    ) -> None:
        _populate_prices(migrated_client, n_bars=5)
        io = ParquetIO(client=migrated_client)

        archive = tmp_path / "backup.parquet"
        io.export_table("prices_ohlcv", archive)

        # Re-import con upsert: righe già presenti sono sovrascritte
        io.import_table("prices_ohlcv", archive, mode="upsert")
        rows = migrated_client.query("SELECT COUNT(*) FROM prices_ohlcv")
        assert rows[0][0] == 5  # Non raddoppiato

    def test_import_replace_clears_first(
        self, migrated_client: DuckDBClient, tmp_path: Path
    ) -> None:
        _populate_prices(migrated_client, n_bars=8)
        io = ParquetIO(client=migrated_client)

        archive = tmp_path / "backup.parquet"
        io.export_query(
            "SELECT * FROM prices_ohlcv LIMIT 3", archive
        )

        n = io.import_table("prices_ohlcv", archive, mode="replace")
        assert n == 3
        # Dopo replace+import di 3 righe: totale = 3 (non 8+3)
        rows = migrated_client.query("SELECT COUNT(*) FROM prices_ohlcv")
        assert rows[0][0] == 3

    def test_import_missing_file_raises(
        self, migrated_client: DuckDBClient, tmp_path: Path
    ) -> None:
        io = ParquetIO(client=migrated_client)
        with pytest.raises(DuckDBError, match="not found"):
            io.import_table("prices_ohlcv", tmp_path / "nothing.parquet")

    def test_import_invalid_mode_raises(
        self, migrated_client: DuckDBClient, tmp_path: Path
    ) -> None:
        _populate_prices(migrated_client, n_bars=1)
        io = ParquetIO(client=migrated_client)
        archive = tmp_path / "x.parquet"
        io.export_table("prices_ohlcv", archive)

        with pytest.raises(ValueError, match="Invalid mode"):
            io.import_table("prices_ohlcv", archive, mode="merge")


class TestDescribeParquet:
    def test_describe_returns_schema_and_row_count(
        self, migrated_client: DuckDBClient, tmp_path: Path
    ) -> None:
        _populate_prices(migrated_client, n_bars=7)
        io = ParquetIO(client=migrated_client)
        archive = tmp_path / "info.parquet"
        io.export_table("prices_ohlcv", archive)

        info = io.describe_parquet(archive)
        assert info["row_count"] == 7
        assert info["file_size_bytes"] > 0

        columns = info["columns"]
        assert isinstance(columns, list)
        column_names = [c[0] for c in columns]
        for expected in ("ticker", "ts", "open", "high", "low", "close", "volume"):
            assert expected in column_names
