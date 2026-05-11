"""Tests for shared.backup_manager."""
from __future__ import annotations

import sqlite3
import tarfile
from pathlib import Path

import pytest

from shared.backup_manager import BackupManager
from shared.db.duckdb_client import DuckDBClient


@pytest.fixture
def populated_duckdb(tmp_duckdb_path: Path) -> Path:
    """DuckDB populated with sample data for backup tests."""
    with DuckDBClient(path=tmp_duckdb_path) as client:
        client.execute("CREATE TABLE t (id INTEGER, name VARCHAR)")
        client.execute("INSERT INTO t VALUES (1, 'alpha'), (2, 'beta'), (3, 'gamma')")
    return tmp_duckdb_path


@pytest.fixture
def populated_sqlite(tmp_sqlite_path: Path) -> Path:
    """SQLite populated with sample data for backup tests."""
    conn = sqlite3.connect(tmp_sqlite_path)
    try:
        conn.execute("CREATE TABLE u (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO u VALUES (1, 'hello'), (2, 'world')")
        conn.commit()
    finally:
        conn.close()
    return tmp_sqlite_path


class TestBackupManager:
    def test_run_backup_creates_archive(
        self,
        populated_duckdb: Path,
        populated_sqlite: Path,
        tmp_backup_dir: Path,
    ) -> None:
        mgr = BackupManager(
            duckdb_path=populated_duckdb,
            sqlite_path=populated_sqlite,
            backup_dir=tmp_backup_dir,
        )
        archive = mgr.run_backup()

        assert archive.exists()
        assert archive.name.startswith("backup_")
        assert archive.suffix == ".gz"

    def test_archive_contains_duckdb_and_sqlite(
        self,
        populated_duckdb: Path,
        populated_sqlite: Path,
        tmp_backup_dir: Path,
    ) -> None:
        mgr = BackupManager(
            duckdb_path=populated_duckdb,
            sqlite_path=populated_sqlite,
            backup_dir=tmp_backup_dir,
        )
        archive = mgr.run_backup()

        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
            # Atteso: backup_TS/duckdb/... e backup_TS/sqlite.db
            assert any("duckdb" in n for n in names), f"duckdb not found in {names}"
            assert any("sqlite.db" in n for n in names), f"sqlite.db not found in {names}"

    def test_sqlite_backup_is_restorable(
        self,
        populated_duckdb: Path,
        populated_sqlite: Path,
        tmp_backup_dir: Path,
        tmp_path: Path,
    ) -> None:
        mgr = BackupManager(
            duckdb_path=populated_duckdb,
            sqlite_path=populated_sqlite,
            backup_dir=tmp_backup_dir,
        )
        archive = mgr.run_backup()

        # Estrai l'archivio in una directory pulita
        restore_dir = tmp_path / "restored"
        restore_dir.mkdir()
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(restore_dir, filter="data")  # type: ignore[arg-type]

        # Trova il file sqlite estratto
        sqlite_files = list(restore_dir.rglob("sqlite.db"))
        assert len(sqlite_files) == 1

        # Verifica integrità dati
        conn = sqlite3.connect(sqlite_files[0])
        try:
            rows = conn.execute("SELECT id, value FROM u ORDER BY id").fetchall()
            assert rows == [(1, "hello"), (2, "world")]
        finally:
            conn.close()

    def test_cleanup_respects_retain_count(
        self,
        populated_duckdb: Path,
        populated_sqlite: Path,
        tmp_backup_dir: Path,
    ) -> None:
        mgr = BackupManager(
            duckdb_path=populated_duckdb,
            sqlite_path=populated_sqlite,
            backup_dir=tmp_backup_dir,
            retain_count=2,
        )

        # Creiamo 4 backup consecutivi. I primi 2 devono essere eliminati.
        # Timestamp basati sull'ora UTC con risoluzione al secondo: aggiungiamo
        # un minimo sleep per assicurare nomi file distinti.
        import time

        archives: list[Path] = []
        for _ in range(4):
            archives.append(mgr.run_backup())
            time.sleep(1.1)

        remaining = mgr.list_backups()
        assert len(remaining) == 2, f"expected 2 remaining, got {len(remaining)}"

    def test_list_backups_sorted_newest_first(
        self,
        populated_duckdb: Path,
        populated_sqlite: Path,
        tmp_backup_dir: Path,
    ) -> None:
        import time

        mgr = BackupManager(
            duckdb_path=populated_duckdb,
            sqlite_path=populated_sqlite,
            backup_dir=tmp_backup_dir,
            retain_count=10,
        )

        first = mgr.run_backup()
        time.sleep(1.1)
        second = mgr.run_backup()

        backups = mgr.list_backups()
        assert backups[0] == second  # Più recente per primo
        assert backups[1] == first

    def test_latest_backup_when_none(self, tmp_backup_dir: Path) -> None:
        mgr = BackupManager(
            duckdb_path=Path("/nonexistent/duckdb"),
            sqlite_path=Path("/nonexistent/sqlite"),
            backup_dir=tmp_backup_dir,
        )
        assert mgr.latest_backup() is None

    def test_missing_source_files_tolerated(
        self, tmp_backup_dir: Path, tmp_path: Path
    ) -> None:
        """Backup should not crash if source DB files don't exist yet."""
        mgr = BackupManager(
            duckdb_path=tmp_path / "missing.duckdb",
            sqlite_path=tmp_path / "missing.sqlite",
            backup_dir=tmp_backup_dir,
        )
        # Non deve sollevare: entrambe le sorgenti vengono loggate e saltate
        archive = mgr.run_backup()
        assert archive.exists()
