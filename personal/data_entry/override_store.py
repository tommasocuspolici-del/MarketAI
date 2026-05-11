"""ManualOverrideStore: override utente per qualsiasi valore API (Rule 43).

Persiste su SQLite (DB applicazione) gli override che l'utente vuole
applicare sopra i valori restituiti dalle API. Pattern d'uso:

    store = ManualOverrideStore()
    final_value, is_override = store.resolve("price", "AAPL", api_value=187.42)
    # Se esiste override attivo per AAPL::price -> ritorna user_value.
    # Altrimenti -> ritorna api_value.

Tabella ``manual_overrides``:
  - id          INTEGER PK
  - entity_type VARCHAR  -- "price", "pe_ratio", "market_cap", ...
  - entity_key  VARCHAR  -- es. "AAPL", "EURUSD"
  - api_value   REAL
  - user_value  REAL
  - note        VARCHAR
  - created_at  TIMESTAMP
  - is_active   BOOLEAN  -- soft-delete (audit trail)

Soft-delete: rimuovere un override imposta ``is_active=0``, non cancella
la riga, mantenendo storia degli override applicati.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock

__version__ = "7.1.0"

__all__ = ["ManualOverride", "ManualOverrideStore"]

# Path di default del DB; configurabile alla costruzione del servizio.
_DEFAULT_DB_PATH = Path("data/marketai_personal.db")
_TABLE = "manual_overrides"


@dataclass(frozen=True, slots=True)
class ManualOverride:
    """Record di un override manuale."""

    id: int
    entity_type: str
    entity_key: str
    api_value: float | None
    user_value: float
    note: str
    created_at: datetime
    is_active: bool


class ManualOverrideStore:
    """CRUD su manual_overrides. Thread-safe (lock interno + WAL SQLite)."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._lock = Lock()
        self._ensure_table()

    # --------------------------------------------------------------- internal
    def _connect(self) -> sqlite3.Connection:
        """Apre una connessione SQLite con row_factory abilitato."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self._db_path),
            detect_types=sqlite3.PARSE_DECLTYPES,
            isolation_level=None,  # autocommit
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _ensure_table(self) -> None:
        """Crea la tabella e l'indice se non esistono."""
        with self._lock, self._connect() as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_TABLE} (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_type VARCHAR NOT NULL,
                    entity_key  VARCHAR NOT NULL,
                    api_value   REAL,
                    user_value  REAL    NOT NULL,
                    note        VARCHAR DEFAULT '',
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active   BOOLEAN DEFAULT 1
                )
                """
            )
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_overrides_active
                ON {_TABLE}(entity_type, entity_key, is_active)
                """
            )

    @staticmethod
    def _row_to_override(row: sqlite3.Row) -> ManualOverride:
        """Converte una riga sqlite3.Row in dataclass ManualOverride."""
        created_at_raw = row["created_at"]
        if isinstance(created_at_raw, str):
            try:
                created_at = datetime.fromisoformat(created_at_raw)
            except ValueError:
                created_at = datetime.utcnow()
        elif isinstance(created_at_raw, datetime):
            created_at = created_at_raw
        else:
            created_at = datetime.utcnow()
        return ManualOverride(
            id=int(row["id"]),
            entity_type=str(row["entity_type"]),
            entity_key=str(row["entity_key"]),
            api_value=float(row["api_value"]) if row["api_value"] is not None else None,
            user_value=float(row["user_value"]),
            note=str(row["note"] or ""),
            created_at=created_at,
            is_active=bool(row["is_active"]),
        )

    # --------------------------------------------------------------- public
    def set(
        self,
        entity_type: str,
        entity_key: str,
        user_value: float,
        *,
        api_value: float | None = None,
        note: str = "",
    ) -> None:
        """Imposta o sostituisce un override.

        Eventuale override precedente viene disattivato (soft-delete).
        """
        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE {_TABLE} SET is_active=0 "
                f"WHERE entity_type=? AND entity_key=? AND is_active=1",
                (entity_type, entity_key),
            )
            conn.execute(
                f"INSERT INTO {_TABLE} "
                f"(entity_type, entity_key, api_value, user_value, note) "
                f"VALUES (?, ?, ?, ?, ?)",
                (entity_type, entity_key, api_value, user_value, note),
            )

    def remove(self, entity_type: str, entity_key: str) -> None:
        """Soft-delete dell'override attivo (ripristina valore API)."""
        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE {_TABLE} SET is_active=0 "
                f"WHERE entity_type=? AND entity_key=? AND is_active=1",
                (entity_type, entity_key),
            )

    def get(
        self, entity_type: str, entity_key: str
    ) -> ManualOverride | None:
        """Ritorna l'override attivo o None."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                f"SELECT * FROM {_TABLE} "
                f"WHERE entity_type=? AND entity_key=? AND is_active=1 "
                f"ORDER BY created_at DESC LIMIT 1",
                (entity_type, entity_key),
            )
            row = cur.fetchone()
        return self._row_to_override(row) if row else None

    def resolve(
        self,
        entity_type: str,
        entity_key: str,
        api_value: float | None,
    ) -> tuple[float | None, bool]:
        """Risolve il valore finale: override se presente, altrimenti API.

        Returns:
            tuple (final_value, is_override).
        """
        override = self.get(entity_type, entity_key)
        if override is not None:
            return override.user_value, True
        return api_value, False

    def list_active(self) -> list[ManualOverride]:
        """Lista tutti gli override attivi (per UI di gestione)."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                f"SELECT * FROM {_TABLE} WHERE is_active=1 "
                f"ORDER BY created_at DESC"
            )
            rows = cur.fetchall()
        return [self._row_to_override(r) for r in rows]

    def history(self, entity_type: str, entity_key: str) -> list[ManualOverride]:
        """Storia completa (anche soft-deleted) di un'entita'."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                f"SELECT * FROM {_TABLE} "
                f"WHERE entity_type=? AND entity_key=? "
                f"ORDER BY created_at DESC",
                (entity_type, entity_key),
            )
            rows = cur.fetchall()
        return [self._row_to_override(r) for r in rows]
