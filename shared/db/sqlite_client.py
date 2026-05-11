"""SQLite client — OLTP layer for transactional/relational data (Rule 13).

Used for: investor profiles, positions (eToro import), cash flow entries,
financial goals, wealth snapshots, alert history.

Design:
  · WAL mode enabled for concurrent read safety.
  · SQLAlchemy engine + session factory (Alembic for migrations).
  · Foreign keys ON.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from shared.constants import SQLITE_PATH
from shared.exceptions import SQLiteError
from shared.logger import get_logger

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator
    from pathlib import Path

__version__ = "6.0.0"

__all__ = ["SQLiteClient", "get_sqlite_client"]

log = get_logger(__name__)


class SQLiteClient:
    """Thin wrapper providing SQLAlchemy engine + raw connection access."""

    def __init__(self, path: Path = SQLITE_PATH) -> None:
        # Garantisce che la directory del DB esista
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path

        # SQLAlchemy URL: usiamo il driver built-in di Python (sqlite3)
        url = f"sqlite:///{path.resolve()}"
        log.info("sqlite.connecting", path=str(path))

        self._engine: Engine = create_engine(
            url,
            echo=False,
            future=True,
            # Check_same_thread=False perché usiamo sessioni distinte per thread
            connect_args={"check_same_thread": False},
        )

        # Applica pragma ogni nuova connessione (WAL + foreign keys)
        event.listens_for(self._engine, "connect")(_apply_pragmas)

        self._session_factory = sessionmaker(
            bind=self._engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            class_=Session,
        )

    # ─── SQLAlchemy accessors ────────────────────────────────────────────
    @property
    def engine(self) -> Engine:
        """Underlying SQLAlchemy engine (for Alembic, migrations, raw SQL)."""
        return self._engine

    @property
    def path(self) -> Path:
        return self._path

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Context-managed ORM session with auto-commit/rollback."""
        sess: Session = self._session_factory()
        try:
            yield sess
            sess.commit()
        except Exception:
            # Rollback + rilancio: mai nascondere errori transazionali
            sess.rollback()
            raise
        finally:
            sess.close()

    # ─── Raw execute (for quick queries or health checks) ────────────────
    def execute(self, sql: str, params: dict[str, Any] | None = None) -> list[tuple[Any, ...]]:
        """Run a raw SQL statement. Returns rows as list of tuples."""
        try:
            with self._engine.begin() as conn:
                result = conn.execute(text(sql), params or {})
                if result.returns_rows:
                    return [tuple(row) for row in result.fetchall()]
                return []
        except Exception as exc:
            raise SQLiteError(f"SQLite execute failed: {exc}\nSQL: {sql[:200]}") from exc

    # ─── Introspection ───────────────────────────────────────────────────
    def list_tables(self) -> list[str]:
        """Return user-defined table names."""
        rows = self.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
        return [r[0] for r in rows]

    # ─── Lifecycle ───────────────────────────────────────────────────────
    def close(self) -> None:
        """Dispose the engine. Safe to call multiple times."""
        self._engine.dispose()
        log.info("sqlite.closed", path=str(self._path))

    def __enter__(self) -> SQLiteClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


# ═══════════════════════════════════════════════════════════════════════════
# Connection-level pragma setter
# ═══════════════════════════════════════════════════════════════════════════
def _apply_pragmas(dbapi_connection: sqlite3.Connection, _connection_record: Any) -> None:
    """Apply standard pragmas to every new SQLite connection.

    · foreign_keys=ON  — respect FK constraints (SQLite default is OFF)
    · journal_mode=WAL — concurrent read-while-write, crash safety
    · synchronous=NORMAL — balance durability vs performance
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════
_INSTANCE: SQLiteClient | None = None


def get_sqlite_client(path: Path | None = None) -> SQLiteClient:
    """Return the process-wide SQLiteClient singleton."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = SQLiteClient(path=path or SQLITE_PATH)
    return _INSTANCE


def reset_sqlite_client() -> None:
    """Close and reset singleton (tests only)."""
    global _INSTANCE
    if _INSTANCE is not None:
        _INSTANCE.close()
        _INSTANCE = None
