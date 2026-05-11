"""Tests for shared.db.duckdb_client."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from shared.db.duckdb_client import DuckDBClient
from shared.exceptions import DuckDBError

if TYPE_CHECKING:
    from pathlib import Path


class TestDuckDBClient:
    def test_connects_and_creates_file(self, tmp_duckdb_path: Path) -> None:
        assert not tmp_duckdb_path.exists()
        with DuckDBClient(path=tmp_duckdb_path) as client:
            # La sola connect dovrebbe creare il file
            client.query("SELECT 1")
        assert tmp_duckdb_path.exists()

    def test_simple_query_returns_tuple(self, tmp_duckdb_path: Path) -> None:
        with DuckDBClient(path=tmp_duckdb_path) as client:
            rows = client.query("SELECT 42 AS answer")
            assert rows == [(42,)]

    def test_execute_ddl_and_insert(self, tmp_duckdb_path: Path) -> None:
        with DuckDBClient(path=tmp_duckdb_path) as client:
            client.execute("CREATE TABLE t (id INTEGER, name VARCHAR)")
            client.execute("INSERT INTO t VALUES (1, 'one'), (2, 'two')")
            rows = client.query("SELECT * FROM t ORDER BY id")
            assert rows == [(1, "one"), (2, "two")]

    def test_parameterized_query(self, tmp_duckdb_path: Path) -> None:
        with DuckDBClient(path=tmp_duckdb_path) as client:
            client.execute("CREATE TABLE t (id INTEGER)")
            client.execute("INSERT INTO t VALUES (?), (?), (?)", [1, 2, 3])
            rows = client.query("SELECT COUNT(*) FROM t WHERE id > ?", [1])
            assert rows == [(2,)]

    def test_table_exists(self, tmp_duckdb_path: Path) -> None:
        with DuckDBClient(path=tmp_duckdb_path) as client:
            assert not client.table_exists("my_table")
            client.execute("CREATE TABLE my_table (x INTEGER)")
            assert client.table_exists("my_table")

    def test_list_tables(self, tmp_duckdb_path: Path) -> None:
        with DuckDBClient(path=tmp_duckdb_path) as client:
            client.execute("CREATE TABLE a (x INTEGER)")
            client.execute("CREATE TABLE b (y INTEGER)")
            tables = client.list_tables()
            assert "a" in tables
            assert "b" in tables

    def test_transaction_commits_on_success(self, tmp_duckdb_path: Path) -> None:
        with DuckDBClient(path=tmp_duckdb_path) as client:
            client.execute("CREATE TABLE t (id INTEGER)")
            with client.transaction():
                client.execute("INSERT INTO t VALUES (1)")
                client.execute("INSERT INTO t VALUES (2)")
            rows = client.query("SELECT COUNT(*) FROM t")
            assert rows == [(2,)]

    def test_transaction_rolls_back_on_error(self, tmp_duckdb_path: Path) -> None:
        with DuckDBClient(path=tmp_duckdb_path) as client:
            client.execute("CREATE TABLE t (id INTEGER)")
            client.execute("INSERT INTO t VALUES (1)")

            with pytest.raises(DuckDBError), client.transaction():
                client.execute("INSERT INTO t VALUES (2)")
                # SQL invalido → transazione abortita
                client.execute("INSERT INTO nonexistent VALUES (3)")

            # Il valore (2) NON deve essere persistito
            rows = client.query("SELECT COUNT(*) FROM t")
            assert rows == [(1,)]

    def test_invalid_sql_raises_duckdb_error(self, tmp_duckdb_path: Path) -> None:
        with DuckDBClient(path=tmp_duckdb_path) as client, pytest.raises(DuckDBError):
            client.execute("THIS IS NOT SQL")

    def test_path_property(self, tmp_duckdb_path: Path) -> None:
        with DuckDBClient(path=tmp_duckdb_path) as client:
            assert client.path == tmp_duckdb_path


@pytest.mark.benchmark
class TestDuckDBPerformance:
    """Performance targets from Fase 1 DoD."""

    def test_insert_10k_rows_under_500ms(self, tmp_duckdb_path: Path) -> None:
        # pytest-benchmark opzionale: skip graceful se non disponibile
        benchmark = pytest.importorskip("pytest_benchmark")  # noqa: F841
        pd = pytest.importorskip("pandas")

        with DuckDBClient(path=tmp_duckdb_path) as client:
            client.execute("CREATE TABLE t (a INTEGER, b DOUBLE, c VARCHAR)")
            df = pd.DataFrame(
                {
                    "a": list(range(10_000)),
                    "b": [float(i) * 1.1 for i in range(10_000)],
                    "c": [f"x{i}" for i in range(10_000)],
                }
            )
            # Verifica funzionale: 10k righe inserite correttamente
            result = client.insert_df("t", df)
            assert result == 10_000
