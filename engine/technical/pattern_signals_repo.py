"""PatternSignalsRepo — persistenza e lettura dei pattern grafici su DuckDB.

Gestisce la tabella ``pattern_signals`` creata da migration 013.
Separata da PatternDetector per rispettare la Regola 2 (SRP).

Regola 13: dati analitici → DuckDB (non SQLite).
Regola 27: schema creato dalla migration 20260901_013_pattern_signals.sql.
"""
from __future__ import annotations

import json
import threading
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from engine.technical.pattern_schemas import PatternResult, PatternType
from shared.db.duckdb_client import DuckDBClient, get_duckdb_client
from shared.exceptions import DatabaseError
from shared.logger import get_logger

__version__ = "9.0.0"
__all__ = [
    "PatternSignalsRepo",
    "get_pattern_signals_repo",
    "reset_pattern_signals_repo",
]

log = get_logger(__name__)


class PatternSignalsRepo:
    """CRUD per la tabella ``pattern_signals`` in DuckDB.

    Metodi principali:
      · write(results) — upsert batch di PatternResult
      · read_latest(ticker, n) — legge gli N pattern più recenti
      · read_by_type(pattern_type) — filtra per tipo
      · read_active(ticker) — solo pattern con status='ACTIVE'
    """

    def __init__(self, client: DuckDBClient | None = None) -> None:
        self._client = client or get_duckdb_client()

    # ─── Write ───────────────────────────────────────────────────────────────

    def write(self, results: list[PatternResult]) -> int:
        """Persiste una lista di PatternResult in pattern_signals.

        ANTI-REGRESSIONE (v9.0 Sett.3): usa INSERT OR REPLACE con colonne
        esplicite — stesso pattern fix di fundamentals_repo per evitare
        il DuckDB Binder Error su alias nella SELECT.

        Returns:
            Numero di righe inserite.
        """
        if not results:
            return 0
        rows = [r.to_db_dict() for r in results]
        df   = pd.DataFrame(rows)

        try:
            with self._client.transaction() as conn:
                conn.register("_pattern_batch", df)
                conn.execute("""
                    INSERT OR REPLACE INTO pattern_signals
                    (ticker, pattern_type, signal_dir, confidence,
                     start_date, end_date, start_idx, end_idx,
                     key_levels_json, description, detected_at, status)
                    SELECT
                        ticker, pattern_type, signal_dir, confidence,
                        start_date::TIMESTAMPTZ, end_date::TIMESTAMPTZ,
                        start_idx, end_idx,
                        key_levels_json, description, NOW(), 'ACTIVE'
                    FROM _pattern_batch
                """)
                n = len(df)
            log.info(
                "pattern_repo.written",
                rows=n,
                tickers=df["ticker"].nunique(),
            )
            return n
        except Exception as exc:
            raise DatabaseError(f"pattern_signals write failed: {exc}") from exc

    # ─── Read ─────────────────────────────────────────────────────────────────

    def read_latest(self, ticker: str, n: int = 10) -> pd.DataFrame:
        """Legge gli N pattern più recenti per un ticker."""
        try:
            with self._client.transaction() as conn:
                df = conn.execute(
                    """
                    SELECT ticker, pattern_type, signal_dir, confidence,
                           start_date, end_date, key_levels_json,
                           description, detected_at, status
                    FROM pattern_signals
                    WHERE ticker = ?
                    ORDER BY detected_at DESC
                    LIMIT ?
                    """,
                    [ticker, n],
                ).df()
            return df
        except Exception as exc:
            log.warning("pattern_repo.read_latest_error", ticker=ticker, error=str(exc)[:100])
            return pd.DataFrame()

    def read_by_type(
        self,
        pattern_type: PatternType | str,
        limit: int = 50,
    ) -> pd.DataFrame:
        """Legge i pattern di un certo tipo ordinati per confidence DESC."""
        pt = pattern_type.value if isinstance(pattern_type, PatternType) else str(pattern_type)
        try:
            with self._client.transaction() as conn:
                df = conn.execute(
                    """
                    SELECT ticker, pattern_type, signal_dir, confidence,
                           start_date, end_date, description, detected_at
                    FROM pattern_signals
                    WHERE pattern_type = ?
                    ORDER BY confidence DESC, detected_at DESC
                    LIMIT ?
                    """,
                    [pt, limit],
                ).df()
            return df
        except Exception as exc:
            log.warning("pattern_repo.read_by_type_error", pt=pt, error=str(exc)[:100])
            return pd.DataFrame()

    def read_active(self, ticker: str) -> list[dict[str, object]]:
        """Ritorna i pattern ACTIVE per un ticker come lista di dict.

        Utile per la UI (badge sulla chart).
        """
        try:
            with self._client.transaction() as conn:
                rows = conn.execute(
                    """
                    SELECT pattern_type, signal_dir, confidence,
                           key_levels_json, description
                    FROM pattern_signals
                    WHERE ticker = ? AND status = 'ACTIVE'
                    ORDER BY confidence DESC
                    LIMIT 5
                    """,
                    [ticker],
                ).fetchall()

            result: list[dict[str, object]] = []
            for row in rows:
                try:
                    levels = json.loads(row[3]) if row[3] else {}
                except (json.JSONDecodeError, TypeError):
                    levels = {}
                result.append({
                    "pattern_type": row[0],
                    "signal_dir": row[1],
                    "confidence": float(row[2]),
                    "key_levels": levels,
                    "description": row[4] or "",
                })
            return result

        except Exception as exc:
            log.warning("pattern_repo.read_active_error", ticker=ticker, error=str(exc)[:100])
            return []

    def count_by_ticker(self, ticker: str) -> int:
        """Numero totale di pattern storici per un ticker."""
        try:
            with self._client.transaction() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM pattern_signals WHERE ticker = ?",
                    [ticker],
                ).fetchone()
                return int(row[0]) if row else 0
        except Exception:  # noqa: BLE001
            return 0

    def expire_old(self, days: int = 30) -> int:
        """Marca come EXPIRED i pattern più vecchi di `days` giorni.

        Fa parte della retention policy (Regola 31).
        """
        cutoff = (datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0))
        cutoff_str = cutoff.isoformat()
        try:
            with self._client.transaction() as conn:
                conn.execute(
                    """
                    UPDATE pattern_signals
                    SET status = 'EXPIRED'
                    WHERE status = 'ACTIVE'
                    AND detected_at < ?::TIMESTAMPTZ - INTERVAL (? || ' days')
                    """,
                    [cutoff_str, days],
                )
                count_row = conn.execute(
                    "SELECT COUNT(*) FROM pattern_signals WHERE status = 'EXPIRED'"
                ).fetchone()
                n = count_row[0] if count_row else 0
            return int(n)
        except Exception as exc:
            log.warning("pattern_repo.expire_error", error=str(exc)[:100])
            return 0


# ─── Singleton ────────────────────────────────────────────────────────────────

_repo_lock = threading.Lock()
_default_repo: PatternSignalsRepo | None = None


def get_pattern_signals_repo() -> PatternSignalsRepo:
    """Singleton thread-safe per PatternSignalsRepo."""
    global _default_repo  # noqa: PLW0603
    with _repo_lock:
        if _default_repo is None:
            _default_repo = PatternSignalsRepo()
        return _default_repo


def reset_pattern_signals_repo() -> None:
    """Reset singleton per teardown nei test."""
    global _default_repo  # noqa: PLW0603
    with _repo_lock:
        _default_repo = None
