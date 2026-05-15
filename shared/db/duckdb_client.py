"""DuckDB client — OLAP layer for large time-series data (Rule 13).

Used for: prices (OHLCV), macro series (FRED/ECB), fundamentals (SEC EDGAR),
sentiment history, backtest results, stress scenarios, quality reports.

Design:
  · Single shared read/write connection per process (DuckDB is in-process).
  · WAL mode-like behavior via transactions.
  · Schema evolution via DuckDBMigrator, NEVER manually (Rule 27).
"""
from __future__ import annotations

from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, Any

import duckdb

from shared.constants import DUCKDB_PATH
from shared.exceptions import DuckDBError
from shared.logger import get_logger
from shared.metrics import metrics

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__version__ = "6.0.0"

__all__ = ["DuckDBClient", "get_duckdb_client"]

log = get_logger(__name__)


class DuckDBClient:
    """Thin wrapper around a DuckDB connection.

    Single instance per process. Use ``get_duckdb_client()`` to obtain it.
    """

    def __init__(self, path: Path = DUCKDB_PATH, read_only: bool = False) -> None:
        # Garantisce che la directory del DB esista prima della connect
        path.parent.mkdir(parents=True, exist_ok=True)

        self._path = path
        self._read_only = read_only
        log.info("duckdb.connecting", path=str(path), read_only=read_only)
        try:
            self._conn: duckdb.DuckDBPyConnection = duckdb.connect(
                database=str(path),
                read_only=read_only,
            )
        except duckdb.Error as exc:
            raise DuckDBError(f"Failed to connect to DuckDB at {path}: {exc}") from exc

        # Configurazione conservativa: privilegia correttezza alla velocità pura
        self._configure_pragma()

    def _configure_pragma(self) -> None:
        """Apply sensible pragmas: memory limit, threads, etc."""
        # Thread count moderato per evitare contesa su CPU consumer-grade
        try:
            self._conn.execute("PRAGMA threads=4")
            self._conn.execute("PRAGMA memory_limit='2GB'")
        except duckdb.Error as exc:
            log.warning("duckdb.pragma_failed", error=str(exc))

    # ─── Core execution ──────────────────────────────────────────────────
    def execute(
        self,
        sql: str,
        params: list[Any] | tuple[Any, ...] | None = None,
    ) -> duckdb.DuckDBPyConnection:
        """Execute a SQL statement (DDL or DML). Returns the cursor."""
        with metrics.timer("duckdb_execute_ms"):
            try:
                if params is not None:
                    return self._conn.execute(sql, params)
                return self._conn.execute(sql)
            except duckdb.Error as exc:
                raise DuckDBError(f"DuckDB execute failed: {exc}\nSQL: {sql[:200]}") from exc

    def query(
        self,
        sql: str,
        params: list[Any] | tuple[Any, ...] | None = None,
    ) -> list[tuple[Any, ...]]:
        """Run SELECT and return all rows as list of tuples."""
        with metrics.timer("duckdb_query_ms"):
            try:
                if params is not None:
                    result = self._conn.execute(sql, params).fetchall()
                else:
                    result = self._conn.execute(sql).fetchall()
                return list(result)
            except duckdb.Error as exc:
                raise DuckDBError(f"DuckDB query failed: {exc}\nSQL: {sql[:200]}") from exc

    def query_df(self, sql: str, params: list[Any] | tuple[Any, ...] | None = None) -> Any:
        """Run SELECT and return a pandas DataFrame (DuckDB native support)."""
        with metrics.timer("duckdb_query_df_ms"):
            try:
                if params is not None:
                    return self._conn.execute(sql, params).df()
                return self._conn.execute(sql).df()
            except duckdb.Error as exc:
                raise DuckDBError(f"DuckDB query_df failed: {exc}") from exc

    # ─── Bulk operations ─────────────────────────────────────────────────
    def register_df(self, name: str, df: Any) -> None:
        """Register a pandas DataFrame as a temporary view for zero-copy ops."""
        try:
            self._conn.register(name, df)
        except duckdb.Error as exc:
            raise DuckDBError(f"Failed to register DataFrame as '{name}': {exc}") from exc

    def unregister_df(self, name: str) -> None:
        """Unregister a previously-registered view."""
        import contextlib

        # Non-fatal: la view potrebbe essere già stata rimossa
        with contextlib.suppress(duckdb.Error):
            self._conn.unregister(name)

    def insert_df(self, table: str, df: Any) -> int:
        """Insert a DataFrame into an existing table. Returns row count inserted."""
        n_rows = len(df)
        if n_rows == 0:
            return 0
        with metrics.timer("duckdb_insert_df_ms", table=table):
            try:
                self._conn.register("__tmp_insert__", df)
                self._conn.execute(f"INSERT INTO {table} SELECT * FROM __tmp_insert__")
                self._conn.unregister("__tmp_insert__")
                metrics.inc("duckdb_write_rows_total", amount=n_rows, table=table)
                return n_rows
            except duckdb.Error as exc:
                raise DuckDBError(f"insert_df into {table} failed: {exc}") from exc

    # ─── Transactions ────────────────────────────────────────────────────
    @contextmanager
    def transaction(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """Context manager for explicit transaction control.

        Yields the raw DuckDB connection so callers can use
        ``with client.transaction() as conn: conn.execute(...)``
        """
        try:
            self._conn.execute("BEGIN TRANSACTION")
            yield self._conn
            self._conn.execute("COMMIT")
        except Exception:
            # Rollback su qualunque errore; poi rilancia per non nascondere bug
            with suppress(duckdb.Error):
                self._conn.execute("ROLLBACK")
            raise

    # ─── Schema introspection ────────────────────────────────────────────
    def table_exists(self, name: str) -> bool:
        """Return True if the given table exists in the main schema."""
        rows = self.query(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ? LIMIT 1",
            [name],
        )
        return len(rows) > 0

    def list_tables(self) -> list[str]:
        """Return all user-defined table names (excludes system schema)."""
        rows = self.query(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_name"
        )
        return [r[0] for r in rows]

    # ─── Lifecycle ───────────────────────────────────────────────────────
    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Raw connection, for code that needs DuckDB-specific APIs."""
        return self._conn

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        """Close the connection. Safe to call multiple times."""
        try:
            self._conn.close()
            log.info("duckdb.closed", path=str(self._path))
        except duckdb.Error as exc:
            log.warning("duckdb.close_failed", error=str(exc))

    def __enter__(self) -> DuckDBClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


# ═══════════════════════════════════════════════════════════════════════════
# Singleton accessor
# ═══════════════════════════════════════════════════════════════════════════
_INSTANCE: DuckDBClient | None = None


def get_duckdb_client(path: Path | None = None, read_only: bool = False) -> DuckDBClient:
    """Return the process-wide DuckDBClient singleton.

    Args:
        path: Override default path. Only honored on first call.
        read_only: Open in read-only mode. Only honored on first call.
    """
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = DuckDBClient(path=path or DUCKDB_PATH, read_only=read_only)
    return _INSTANCE


def reset_duckdb_client() -> None:
    """Close and reset the singleton (tests only)."""
    global _INSTANCE
    if _INSTANCE is not None:
        _INSTANCE.close()
        _INSTANCE = None
