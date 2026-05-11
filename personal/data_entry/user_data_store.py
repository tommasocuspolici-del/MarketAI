"""UserDataStore: persistenza locale di dati editabili dall'utente (Rule 41).

Risolve il problema "non posso modificare patrimonio / obiettivi" della v6:
le pagine personal v6 mostravano valori hardcoded perche' non c'era
storage per dati editabili. Questo modulo fornisce un singolo punto di
storage JSON-su-SQLite per tutte le entita' personal.

Tabella SQLite: ``user_data``
  - entity_type   VARCHAR  -- "position", "goal", "asset", "liability",
                              "cashflow_entry", "investor_profile", "portfolio_summary"
  - entity_id     VARCHAR  -- UUID o slug univoco
  - payload_json  TEXT     -- corpo JSON della entita'
  - created_at    TIMESTAMP
  - updated_at    TIMESTAMP

Pattern d'uso::

    store = UserDataStore()
    store.upsert("goal", "goal-123", {"name": "Casa", "target": 80_000, ...})
    goals = store.list_by_type("goal")
    store.delete("goal", "goal-123")

I form personal/data_entry/ usano questo store. Le pagine UI lo usano per
visualizzare e modificare dati.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

__version__ = "7.2.0"

__all__ = [
    "UserDataRecord",
    "UserDataStore",
    "get_default_store",
    "new_id",
    "reset_default_store",
]

# v7.2 (fix B9): path NON piu' relativo. _resolve_default_db_path() risolve
# il percorso assoluto in modo robusto (env var > project root > CWD fallback)
# cosi' save_asset() e list_assets() finiscono SEMPRE sullo stesso DB anche
# se il working directory differisce tra Streamlit process e fixture test.
_TABLE = "user_data"
_ENV_VAR = "MARKETAI_PERSONAL_DB"


def _resolve_default_db_path() -> Path:
    """Risolve il path canonico del DB personale.

    Priorita':
      1. Env var ``MARKETAI_PERSONAL_DB`` (override esplicito test/CI)
      2. ``<project_root>/data/marketai_personal.db`` (canonico, dev/prod)
         dove project_root e' la dir che contiene ``pyproject.toml``
      3. Fallback: ``data/marketai_personal.db`` relativo al CWD

    Idempotente: chiamare piu' volte ritorna stesso path stabile.
    """
    env_path = os.environ.get(_ENV_VAR, "").strip()
    if env_path:
        p = Path(env_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    # Cerca pyproject.toml risalendo da __file__
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").is_file():
            db_dir = parent / "data"
            db_dir.mkdir(parents=True, exist_ok=True)
            return db_dir / "marketai_personal.db"

    # Fallback: data/ in CWD (comportamento legacy)
    return Path("data/marketai_personal.db")


_DEFAULT_DB_PATH = _resolve_default_db_path()


def new_id() -> str:
    """Genera un id univoco breve (UUID4 senza trattini)."""
    return uuid.uuid4().hex[:16]


@dataclass(frozen=True, slots=True)
class UserDataRecord:
    """Wrapper di un record di user_data."""

    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class UserDataStore:
    """CRUD generico su user_data. Thread-safe."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._lock = Lock()
        self._ensure_table()

    # ------------------------------------------------------------- internal
    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self._db_path),
            detect_types=sqlite3.PARSE_DECLTYPES,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _ensure_table(self) -> None:
        """Crea tabella se non esiste."""
        with self._lock, self._connect() as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_TABLE} (
                    entity_type   VARCHAR NOT NULL,
                    entity_id     VARCHAR NOT NULL,
                    payload_json  TEXT    NOT NULL,
                    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (entity_type, entity_id)
                )
                """
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_user_data_type "
                f"ON {_TABLE}(entity_type)"
            )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> UserDataRecord:
        """Converte una riga sqlite3.Row in UserDataRecord."""
        return UserDataRecord(
            entity_type=str(row["entity_type"]),
            entity_id=str(row["entity_id"]),
            payload=json.loads(row["payload_json"]),
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
        )

    # ------------------------------------------------------------- public
    def upsert(
        self,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Inserisce o aggiorna un record. Aggiorna updated_at."""
        payload_json = json.dumps(payload, default=str, ensure_ascii=False)
        now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
        with self._lock, self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {_TABLE} (entity_type, entity_id, payload_json,
                                      created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at   = excluded.updated_at
                """,
                (entity_type, entity_id, payload_json, now, now),
            )

    def get(
        self, entity_type: str, entity_id: str
    ) -> UserDataRecord | None:
        """Ritorna il record o None."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                f"SELECT * FROM {_TABLE} WHERE entity_type=? AND entity_id=?",
                (entity_type, entity_id),
            )
            row = cur.fetchone()
        return self._row_to_record(row) if row else None

    def list_by_type(self, entity_type: str) -> list[UserDataRecord]:
        """Tutti i record di un certo tipo, ordinati per created_at desc."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                f"SELECT * FROM {_TABLE} WHERE entity_type=? "
                f"ORDER BY created_at DESC",
                (entity_type,),
            )
            rows = cur.fetchall()
        return [self._row_to_record(r) for r in rows]

    def delete(self, entity_type: str, entity_id: str) -> bool:
        """Cancella un record. Ritorna True se ha cancellato qualcosa."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                f"DELETE FROM {_TABLE} WHERE entity_type=? AND entity_id=?",
                (entity_type, entity_id),
            )
            return cur.rowcount > 0

    def delete_all_of_type(self, entity_type: str) -> int:
        """Cancella tutti i record di un tipo. Ritorna numero record cancellati."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                f"DELETE FROM {_TABLE} WHERE entity_type=?",
                (entity_type,),
            )
            return cur.rowcount

    def count(self, entity_type: str) -> int:
        """Numero record di un tipo."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                f"SELECT COUNT(*) AS n FROM {_TABLE} WHERE entity_type=?",
                (entity_type,),
            )
            row = cur.fetchone()
        return int(row["n"]) if row else 0


def _parse_dt(value: Any) -> datetime:
    """Parser tollerante di vari formati timestamp SQLite."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.utcnow()


# ─────────────────────────────────────────────────── singleton (v7.2)
# v7.2 (fix B9): singleton del UserDataStore. Senza questo, ogni
# invocazione di save_asset() / list_assets() / save_goal() creava una
# nuova istanza e (se il path era relativo) potevano finire su DB diversi.
# get_default_store() viene usato come default da networth_editor,
# goal_form, ecc. ma e' SEMPRE OVERRIDABILE passando ``store=`` esplicito.
_default_store: UserDataStore | None = None
_default_store_lock = Lock()


def get_default_store() -> UserDataStore:
    """Ritorna il singleton UserDataStore per l'app corrente.

    L'istanza viene creata al primo accesso. Path risolto via
    _resolve_default_db_path(): rispetta l'env var MARKETAI_PERSONAL_DB
    se settata. Thread-safe via lock.

    NB: i test devono passare ``store=`` esplicito ai moduli (form, editor)
    e/o chiamare ``reset_default_store()`` nei teardown. Non riusano mai
    questo singleton in fixture.
    """
    global _default_store  # noqa: PLW0603 -- singleton pattern voluto
    with _default_store_lock:
        if _default_store is None:
            _default_store = UserDataStore()
    return _default_store


def reset_default_store() -> None:
    """Resetta il singleton (utile in test teardown).

    Dopo questa chiamata, il prossimo get_default_store() ricrea l'istanza
    rileggendo eventuali nuove env var (MARKETAI_PERSONAL_DB).
    """
    global _default_store  # noqa: PLW0603
    with _default_store_lock:
        _default_store = None
