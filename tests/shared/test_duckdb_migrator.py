"""Tests for shared.db.duckdb_migrator."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from shared.db.duckdb_client import DuckDBClient
from shared.db.duckdb_migrator import DuckDBMigrator, _split_sql_statements
from shared.exceptions import MigrationError

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    """Empty migrations directory for tests."""
    d = tmp_path / "migrations"
    d.mkdir()
    return d


def _write_migration(dir_: Path, name: str, sql: str) -> Path:
    path = dir_ / name
    path.write_text(sql, encoding="utf-8")
    return path


class TestSplitSqlStatements:
    def test_simple_split(self) -> None:
        sql = "CREATE TABLE a (x INT); CREATE TABLE b (y INT);"
        stmts = _split_sql_statements(sql)
        assert len(stmts) == 2
        assert stmts[0].startswith("CREATE TABLE a")
        assert stmts[1].startswith("CREATE TABLE b")

    def test_ignores_comment_lines(self) -> None:
        sql = "-- this is a comment\nCREATE TABLE a (x INT);\n-- trailing\n"
        stmts = _split_sql_statements(sql)
        assert len(stmts) == 1
        assert "CREATE TABLE a" in stmts[0]

    def test_strips_empty_trailing(self) -> None:
        sql = "CREATE TABLE a (x INT);;; "
        stmts = _split_sql_statements(sql)
        assert len(stmts) == 1


class TestDuckDBMigrator:
    def test_up_to_date_returns_zero(
        self, tmp_duckdb_path: Path, migrations_dir: Path
    ) -> None:
        client = DuckDBClient(path=tmp_duckdb_path)
        try:
            migrator = DuckDBMigrator(client=client, migrations_dir=migrations_dir)
            applied = migrator.apply_pending()
            assert applied == 0
        finally:
            client.close()

    def test_applies_single_migration(
        self, tmp_duckdb_path: Path, migrations_dir: Path
    ) -> None:
        _write_migration(
            migrations_dir,
            "20260401_001_create_foo.sql",
            "CREATE TABLE foo (id INTEGER PRIMARY KEY, name VARCHAR);",
        )
        client = DuckDBClient(path=tmp_duckdb_path)
        try:
            migrator = DuckDBMigrator(client=client, migrations_dir=migrations_dir)
            applied = migrator.apply_pending()
            assert applied == 1

            # Verifica che la tabella sia stata creata
            assert client.table_exists("foo")

            # Verifica registrazione in duckdb_schema_version
            rows = client.query(
                "SELECT version FROM duckdb_schema_version ORDER BY version"
            )
            assert rows == [("20260401_001_create_foo",)]
        finally:
            client.close()

    def test_applies_multiple_migrations_in_order(
        self, tmp_duckdb_path: Path, migrations_dir: Path
    ) -> None:
        _write_migration(
            migrations_dir,
            "20260401_001_first.sql",
            "CREATE TABLE first_table (id INTEGER);",
        )
        _write_migration(
            migrations_dir,
            "20260402_002_second.sql",
            "CREATE TABLE second_table (id INTEGER);",
        )
        _write_migration(
            migrations_dir,
            "20260403_003_third.sql",
            "ALTER TABLE second_table ADD COLUMN name VARCHAR;",
        )

        client = DuckDBClient(path=tmp_duckdb_path)
        try:
            migrator = DuckDBMigrator(client=client, migrations_dir=migrations_dir)
            applied = migrator.apply_pending()
            assert applied == 3

            assert client.table_exists("first_table")
            assert client.table_exists("second_table")

            # Verifica che la colonna aggiunta dalla 3rd migration esista
            rows = client.query("SELECT id, name FROM second_table LIMIT 0")
            assert rows == []  # query valida, nessuna riga

            # Ordine di applicazione corretto
            versions = client.query(
                "SELECT version FROM duckdb_schema_version ORDER BY applied_at"
            )
            assert len(versions) == 3
            assert versions[0][0] == "20260401_001_first"
            assert versions[2][0] == "20260403_003_third"
        finally:
            client.close()

    def test_idempotent_apply(
        self, tmp_duckdb_path: Path, migrations_dir: Path
    ) -> None:
        _write_migration(
            migrations_dir,
            "20260401_001_only.sql",
            "CREATE TABLE only_one (id INTEGER);",
        )
        client = DuckDBClient(path=tmp_duckdb_path)
        try:
            migrator = DuckDBMigrator(client=client, migrations_dir=migrations_dir)

            # Prima applicazione
            assert migrator.apply_pending() == 1
            # Seconda chiamata deve essere no-op
            assert migrator.apply_pending() == 0

            # Tabella ancora esiste
            assert client.table_exists("only_one")
        finally:
            client.close()

    def test_failing_migration_rolls_back(
        self, tmp_duckdb_path: Path, migrations_dir: Path
    ) -> None:
        # 2ª migration ha SQL invalido → rollback completo
        _write_migration(
            migrations_dir,
            "20260401_001_good.sql",
            "CREATE TABLE good_table (id INTEGER);",
        )
        _write_migration(
            migrations_dir,
            "20260402_002_bad.sql",
            "CREATE TABLE x (id INT); THIS IS GARBAGE SQL;",
        )

        client = DuckDBClient(path=tmp_duckdb_path)
        try:
            migrator = DuckDBMigrator(client=client, migrations_dir=migrations_dir)

            with pytest.raises(MigrationError, match="20260402_002_bad"):
                migrator.apply_pending()

            # La 1ª migration DEVE essere già committata (transazione separata)
            assert client.table_exists("good_table")

            # La 2ª NON deve essere registrata
            versions = client.query("SELECT version FROM duckdb_schema_version")
            assert len(versions) == 1
            assert versions[0][0] == "20260401_001_good"
        finally:
            client.close()

    def test_get_pending_returns_remaining(
        self, tmp_duckdb_path: Path, migrations_dir: Path
    ) -> None:
        _write_migration(
            migrations_dir,
            "20260401_001_first.sql",
            "CREATE TABLE first (id INT);",
        )
        _write_migration(
            migrations_dir,
            "20260402_002_second.sql",
            "CREATE TABLE second (id INT);",
        )

        client = DuckDBClient(path=tmp_duckdb_path)
        try:
            migrator = DuckDBMigrator(client=client, migrations_dir=migrations_dir)

            pending = migrator.get_pending_migrations()
            assert len(pending) == 2

            migrator.apply_pending()

            # Nessuna migration rimanente
            pending_after = migrator.get_pending_migrations()
            assert pending_after == []
        finally:
            client.close()

    def test_works_on_real_initial_schema(
        self, tmp_duckdb_path: Path
    ) -> None:
        """Applica la migration reale 20260401_001_initial_schema.sql."""
        from shared.constants import MIGRATIONS_DUCKDB_DIR

        client = DuckDBClient(path=tmp_duckdb_path)
        try:
            migrator = DuckDBMigrator(client=client, migrations_dir=MIGRATIONS_DUCKDB_DIR)
            applied = migrator.apply_pending()

            # Almeno 1 migration deve essere applicata (initial schema)
            assert applied >= 1

            # Le tabelle chiave devono esistere
            for table in [
                "prices_ohlcv",
                "macro_series",
                "fundamentals",
                "sentiment_observations",
                "data_quality_reports",
                "backtest_results",
                "stress_scenarios",
                "correlations",
            ]:
                assert client.table_exists(table), f"table '{table}' missing"
        finally:
            client.close()
