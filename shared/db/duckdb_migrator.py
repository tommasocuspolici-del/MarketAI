"""DuckDB migrations manager (Rule 27).

DuckDB does NOT integrate with Alembic. We use a simple Flyway-style
system based on versioned SQL files tracked in a dedicated
``duckdb_schema_version`` table.

File naming convention:
    YYYYMMDD_NNN_description.sql

Examples:
    20260401_001_initial_schema.sql
    20260415_002_add_correlations_table.sql
    20260520_003_add_indexes.sql

Behavior:
  1. Read applied versions from ``duckdb_schema_version``.
  2. Find .sql files not yet applied (alphabetical order == chronological).
  3. Apply each in a transaction (DuckDB supports DDL transactions).
  4. Record the version once it succeeds.

Idempotent: re-running apply_pending() after a full migration is a no-op.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from shared.constants import MIGRATIONS_DUCKDB_DIR
from shared.db.duckdb_client import DuckDBClient, get_duckdb_client
from shared.exceptions import MigrationError
from shared.logger import get_logger

if TYPE_CHECKING:
    from pathlib import Path

__version__ = "6.0.0"

__all__ = ["DuckDBMigrator", "run_pending_migrations"]

log = get_logger(__name__)

_VERSION_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS duckdb_schema_version (
    version     VARCHAR PRIMARY KEY,
    description VARCHAR NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
""".strip()


class DuckDBMigrator:
    """Applies DuckDB migrations in chronological order."""

    def __init__(
        self,
        client: DuckDBClient | None = None,
        migrations_dir: Path | None = None,
    ) -> None:
        self._client = client or get_duckdb_client()
        self._dir = migrations_dir or MIGRATIONS_DUCKDB_DIR
        self._ensure_version_table()

    def _ensure_version_table(self) -> None:
        """Create the tracking table if it does not exist yet."""
        self._client.execute(_VERSION_TABLE_DDL)

    # ─── Queries ─────────────────────────────────────────────────────────
    def get_applied_versions(self) -> set[str]:
        """Return the set of migration versions already applied."""
        rows = self._client.query("SELECT version FROM duckdb_schema_version")
        return {row[0] for row in rows}

    def discover_migration_files(self) -> list[Path]:
        """Return every *.sql file under the migrations dir, sorted."""
        if not self._dir.exists():
            log.warning("duckdb_migrator.dir_missing", path=str(self._dir))
            return []
        # Ordine alfabetico = ordine cronologico grazie al prefisso YYYYMMDD_NNN
        return sorted(self._dir.glob("*.sql"))

    def get_pending_migrations(self) -> list[Path]:
        """Return migration files not yet applied."""
        applied = self.get_applied_versions()
        return [f for f in self.discover_migration_files() if f.stem not in applied]

    # ─── Application ─────────────────────────────────────────────────────
    def apply_pending(self) -> int:
        """Apply all pending migrations.

        Returns:
            Number of migrations actually applied.

        Raises:
            MigrationError: On first failing migration. State is rolled back.
        """
        pending = self.get_pending_migrations()
        if not pending:
            log.info("duckdb_migrator.up_to_date")
            return 0

        log.info("duckdb_migrator.pending_found", count=len(pending))
        for migration_file in pending:
            self._apply_one(migration_file)

        log.info("duckdb_migrator.complete", applied=len(pending))
        return len(pending)

    def _apply_one(self, migration_file: Path) -> None:
        """Apply a single migration file in a transaction."""
        version = migration_file.stem
        description = migration_file.name

        log.info("duckdb_migrator.applying", version=version)
        sql_content = migration_file.read_text(encoding="utf-8")

        try:
            with self._client.transaction():
                # DuckDB accetta più statement separati da `;` in un unico execute
                # ma per sicurezza e migliore diagnostica li splittiamo esplicitamente
                for stmt in _split_sql_statements(sql_content):
                    self._client.execute(stmt)

                # Registrazione versione solo se tutte le DDL sono passate
                self._client.execute(
                    "INSERT INTO duckdb_schema_version (version, description) VALUES (?, ?)",
                    [version, description],
                )
        except Exception as exc:
            # Logga contesto, poi rilancia come MigrationError per identificazione
            log.error("duckdb_migrator.failed", version=version, error=str(exc))
            raise MigrationError(
                f"Migration {version} failed and was rolled back: {exc}"
            ) from exc

        log.info("duckdb_migrator.applied", version=version)


def _split_sql_statements(sql_content: str) -> list[str]:
    """Split a SQL file into individual statements.

    Handles:
      · Comments with ``--``
      · Multi-line statements
      · Trailing semicolons
    Does NOT handle:
      · Semicolons inside string literals (unusual in schema DDL)
      · ``$$ ... $$`` dollar-quoting (not used in this project)
    """
    # Rimuove linee di solo commento per pulizia (non altera semantica)
    cleaned_lines: list[str] = []
    for line in sql_content.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        cleaned_lines.append(line)
    joined = "\n".join(cleaned_lines)

    statements = [s.strip() for s in joined.split(";")]
    return [s for s in statements if s]


# ═══════════════════════════════════════════════════════════════════════════
# Module-level convenience
# ═══════════════════════════════════════════════════════════════════════════
def run_pending_migrations() -> int:
    """Top-level entry point: apply pending DuckDB migrations.

    Called by the Makefile target ``migrate`` and at application startup.
    """
    migrator = DuckDBMigrator()
    return migrator.apply_pending()
