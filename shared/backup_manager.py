"""Backup manager (operational anti-pattern countermeasure).

DuckDB has no native backup like SQLite, so we use:
  1. DuckDB EXPORT DATABASE → folder with Parquet + schema SQL
  2. SQLite → copy .sqlite file (via backup API for consistency)
  3. Compress everything into a timestamped .tar.gz
  4. Retention: keep last N backups, delete older ones

Configuration via env:
  BACKUP_DIR            (default: data/backups)
  BACKUP_RETAIN_COUNT   (default: 10)
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tarfile
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from shared.constants import BACKUP_DIR, DUCKDB_PATH, SQLITE_PATH
from shared.exceptions import BackupError
from shared.logger import get_logger

if TYPE_CHECKING:
    from pathlib import Path

__version__ = "6.0.0"

__all__ = ["BackupManager"]

log = get_logger(__name__)

_DEFAULT_RETAIN_COUNT: int = 10
_BYTES_PER_MB: int = 1_048_576


class BackupManager:
    """Performs point-in-time backups of DuckDB + SQLite.

    Each ``run_backup()`` call produces a single tar.gz file named
    ``backup_YYYYMMDD_HHMMSS.tar.gz`` in the backup directory.
    """

    def __init__(
        self,
        duckdb_path: Path | None = None,
        sqlite_path: Path | None = None,
        backup_dir: Path | None = None,
        retain_count: int | None = None,
    ) -> None:
        # Preferisci valori espliciti; fallback su constants + env
        self._duckdb_path = duckdb_path or DUCKDB_PATH
        self._sqlite_path = sqlite_path or SQLITE_PATH
        self._backup_dir = backup_dir or BACKUP_DIR

        env_retain = os.getenv("BACKUP_RETAIN_COUNT")
        self._retain_count = retain_count or (
            int(env_retain) if env_retain else _DEFAULT_RETAIN_COUNT
        )

        self._backup_dir.mkdir(parents=True, exist_ok=True)

    # ─── Main entry point ────────────────────────────────────────────────
    def run_backup(self) -> Path:
        """Execute a full backup of DuckDB + SQLite.

        Returns:
            Path to the created .tar.gz archive.

        Raises:
            BackupError: If any step fails.
        """
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        staging = self._backup_dir / f"backup_{ts}"
        staging.mkdir()

        try:
            self._export_duckdb(staging)
            self._copy_sqlite(staging)
            archive = self._compress(staging, ts)
        except Exception as exc:
            # Pulizia area di staging se qualcosa fallisce a metà strada
            shutil.rmtree(staging, ignore_errors=True)
            raise BackupError(f"Backup failed: {exc}") from exc

        # Pulizia staging dopo compressione riuscita
        shutil.rmtree(staging, ignore_errors=True)

        self._cleanup_old_backups()

        size_mb = archive.stat().st_size / _BYTES_PER_MB
        log.info("backup.completed", path=str(archive), size_mb=round(size_mb, 2))
        return archive

    # ─── Components ──────────────────────────────────────────────────────
    def _export_duckdb(self, staging: Path) -> None:
        """Export DuckDB database using EXPORT DATABASE."""
        if not self._duckdb_path.exists():
            log.warning("backup.duckdb_missing", path=str(self._duckdb_path))
            return

        # Import locale per evitare dipendenza a livello di modulo
        import duckdb

        target = staging / "duckdb"
        target.mkdir()
        # EXPORT DATABASE richiede path con forward-slash anche su Windows
        export_path = str(target).replace("\\", "/")
        with duckdb.connect(str(self._duckdb_path), read_only=True) as conn:
            conn.execute(f"EXPORT DATABASE '{export_path}' (FORMAT PARQUET)")
        log.info("backup.duckdb_exported", path=str(target))

    def _copy_sqlite(self, staging: Path) -> None:
        """Copy SQLite database using the online backup API."""
        if not self._sqlite_path.exists():
            log.warning("backup.sqlite_missing", path=str(self._sqlite_path))
            return

        target = staging / "sqlite.db"
        # sqlite3 backup API garantisce consistenza anche con scritture concorrenti
        src = sqlite3.connect(str(self._sqlite_path))
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        log.info("backup.sqlite_copied", path=str(target))

    def _compress(self, staging: Path, ts: str) -> Path:
        """Compress the staging folder into a timestamped tar.gz."""
        archive = self._backup_dir / f"backup_{ts}.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(staging, arcname=f"backup_{ts}")
        return archive

    def _cleanup_old_backups(self) -> None:
        """Keep only the ``retain_count`` most recent backup archives."""
        archives = sorted(
            self._backup_dir.glob("backup_*.tar.gz"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in archives[self._retain_count :]:
            try:
                old.unlink()
                log.info("backup.deleted_old", path=str(old))
            except OSError as exc:
                log.warning("backup.cleanup_failed", path=str(old), error=str(exc))

    # ─── Restore (skeleton) ──────────────────────────────────────────────
    def list_backups(self) -> list[Path]:
        """Return available backup archives, newest first."""
        return sorted(
            self._backup_dir.glob("backup_*.tar.gz"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    def latest_backup(self) -> Path | None:
        """Return the most recent backup, if any."""
        backups = self.list_backups()
        return backups[0] if backups else None
