"""Parquet import / export for DuckDB tables.

Used by:
  · BackupManager (archive creation via COPY to Parquet)
  · Phase 3 bulk loading (FRED / SEC EDGAR landing zone)
  · Manual data import from external sources

Rule 12 still applies: imports must go through cleaning + validation
BEFORE landing in production tables. This module only handles the
physical transfer; the fetcher orchestrates the pipeline.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from shared.db.duckdb_client import DuckDBClient, get_duckdb_client
from shared.exceptions import DuckDBError
from shared.logger import get_logger
from shared.metrics import metrics

if TYPE_CHECKING:
    from pathlib import Path

__version__ = "7.2.0"

__all__ = ["ParquetIO", "get_parquet_io"]

log = get_logger(__name__)


class ParquetIO:
    """Export / import DuckDB tables as Parquet files."""

    def __init__(self, client: DuckDBClient | None = None) -> None:
        self._client = client or get_duckdb_client()

    # ─── Export ──────────────────────────────────────────────────────────
    def export_table(self, table: str, output_path: Path) -> Path:
        """Export a whole table to a single Parquet file.

        Args:
            table: Source table name.
            output_path: Destination .parquet file (created or overwritten).

        Returns:
            The output path, for chaining.
        """
        if not self._client.table_exists(table):
            raise DuckDBError(f"Cannot export: table '{table}' does not exist")

        # Crea la directory padre se necessario (idempotente)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # DuckDB richiede forward-slash anche su Windows
        path_str = str(output_path).replace("\\", "/")

        with metrics.timer("parquet_export_ms", table=table):
            self._client.execute(
                f"COPY (SELECT * FROM {table}) TO '{path_str}' (FORMAT PARQUET)"
            )

        size_bytes = output_path.stat().st_size if output_path.exists() else 0
        log.info(
            "parquet.exported",
            table=table,
            path=str(output_path),
            size_mb=round(size_bytes / 1_048_576, 2),
        )
        return output_path

    def export_query(self, sql: str, output_path: Path) -> Path:
        """Export the result of an arbitrary SELECT to Parquet."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        path_str = str(output_path).replace("\\", "/")

        with metrics.timer("parquet_export_query_ms"):
            # Wrapping in CTE evita conflitti se la query utente ha già una CTE
            self._client.execute(f"COPY ({sql}) TO '{path_str}' (FORMAT PARQUET)")

        log.info("parquet.query_exported", path=str(output_path))
        return output_path

    # ─── Import ──────────────────────────────────────────────────────────
    def import_table(
        self,
        table: str,
        input_path: Path,
        mode: str = "append",
    ) -> int:
        """Import a Parquet file into an existing table.

        Args:
            table: Destination table (must already exist; use migrations
                to create the schema first).
            input_path: Path to .parquet file.
            mode: "append" (INSERT), "replace" (DELETE then INSERT), or
                "upsert" (INSERT OR REPLACE — requires PK on table).

        Returns:
            Number of rows inserted.
        """
        if not input_path.exists():
            raise DuckDBError(f"Parquet file not found: {input_path}")
        if not self._client.table_exists(table):
            raise DuckDBError(f"Target table '{table}' does not exist")
        if mode not in {"append", "replace", "upsert"}:
            raise ValueError(f"Invalid mode: {mode!r}. Use 'append', 'replace', 'upsert'.")

        path_str = str(input_path).replace("\\", "/")

        # Conta righe nel file Parquet prima dell'import (per il return value)
        count_rows = self._client.query(
            f"SELECT COUNT(*) FROM read_parquet('{path_str}')"
        )
        n_rows = int(count_rows[0][0]) if count_rows else 0
        if n_rows == 0:
            log.info("parquet.import_empty", path=str(input_path))
            return 0

        # BUGFIX v7.2.4 (definitivo): il mode "replace" NON usa transazione.
        # Problema DuckDB MVCC: DELETE + INSERT con stesse PK nella stessa
        # transazione fallisce con ConstraintException "Duplicate key" perché
        # il delete-marker non è ancora committed quando l'INSERT viene valutato.
        # TRUNCATE non funziona perché è DDL (auto-commit, poi INSERT isolato).
        # Soluzione: DELETE e INSERT come statement separati fuori transazione.
        # Per "append" e "upsert" manteniamo la transazione per atomicità.
        if mode == "replace":
            with metrics.timer("parquet_import_ms", table=table, mode=mode):
                self._client.execute(f"DELETE FROM {table}")
                self._client.execute(
                    f"INSERT INTO {table} SELECT * FROM read_parquet('{path_str}')"
                )
        else:
            insert_verb = "INSERT OR REPLACE INTO" if mode == "upsert" else "INSERT INTO"
            with (
                metrics.timer("parquet_import_ms", table=table, mode=mode),
                self._client.transaction(),
            ):
                self._client.execute(
                    f"{insert_verb} {table} SELECT * FROM read_parquet('{path_str}')"
                )

        metrics.inc("parquet_rows_imported_total", amount=n_rows, table=table)
        log.info(
            "parquet.imported",
            table=table,
            path=str(input_path),
            rows=n_rows,
            mode=mode,
        )
        return n_rows

    # ─── Introspection ───────────────────────────────────────────────────
    def describe_parquet(self, input_path: Path) -> dict[str, object]:
        """Read a Parquet file's metadata without importing it."""
        if not input_path.exists():
            raise DuckDBError(f"Parquet file not found: {input_path}")

        path_str = str(input_path).replace("\\", "/")
        schema_rows = self._client.query(
            f"DESCRIBE SELECT * FROM read_parquet('{path_str}')"
        )
        count_rows = self._client.query(
            f"SELECT COUNT(*) FROM read_parquet('{path_str}')"
        )
        return {
            "path": str(input_path),
            "row_count": int(count_rows[0][0]) if count_rows else 0,
            # schema è [(column_name, column_type, null, key, default, extra), ...]
            "columns": [(row[0], row[1]) for row in schema_rows],
            "file_size_bytes": input_path.stat().st_size,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════
_INSTANCE: ParquetIO | None = None


def get_parquet_io() -> ParquetIO:
    """Return the process-wide ParquetIO singleton."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ParquetIO()
    return _INSTANCE


def reset_parquet_io() -> None:
    """Reset the singleton (tests only)."""
    global _INSTANCE
    _INSTANCE = None
