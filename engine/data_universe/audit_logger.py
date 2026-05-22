"""Audit Logger — log append-only di tutte le operazioni di fetch e write.

Ogni operazione di fetch o scrittura nel DB viene tracciata nella tabella
audit_log per audit trail completo, debug e monitoraggio della qualità dati.

Regola 12: solo scritture/letture DuckDB; nessuna API fetch.
Regola 19: tutti i timestamp UTC-aware.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import pandas as pd

from shared.logger import get_logger
from shared.resilience.error_policy import apply_error_policy

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["AuditLogger"]

log = get_logger(__name__)

_TABLE = "audit_log"

# Valori ammessi per il campo outcome
_OUTCOME_OK = "ok"
_OUTCOME_ERROR = "error"
_OUTCOME_PARTIAL = "partial"


class AuditLogger:
    """Scrive entry append-only nella tabella audit_log in DuckDB.

    Args:
        client: DuckDBClient per le operazioni sul DB.

    Esempio::

        from shared.db.duckdb_client import get_duckdb_client
        from engine.data_universe.audit_logger import AuditLogger

        al = AuditLogger(client=get_duckdb_client())
        al.log_fetch(
            source="fred",
            endpoint="ICSA",
            record_count=52,
            duration_ms=1430.0,
            outcome="ok",
        )
        df = al.get_recent(hours=24)
    """

    def __init__(self, client: DuckDBClient) -> None:
        self._client = client

    # ─── Write operations ────────────────────────────────────────────────

    @apply_error_policy(
        level="RECOVER",
        fallback=None,
        context="AuditLogger.log_fetch",
    )
    def log_fetch(
        self,
        source: str,
        endpoint: str,
        record_count: int = 0,
        duration_ms: float = 0.0,
        outcome: str = _OUTCOME_OK,
        error_msg: str | None = None,
        data_hash: str | None = None,
    ) -> None:
        """Registra un evento di fetch dati dall'esterno.

        Args:
            source: Provider (es. "fred", "yfinance", "ecb").
            endpoint: Serie o endpoint specifico (es. "ICSA", "/stats/exr").
            record_count: Numero di record ricevuti.
            duration_ms: Durata dell'operazione in millisecondi.
            outcome: Esito ("ok", "error", "partial").
            error_msg: Messaggio di errore se outcome != "ok".
            data_hash: SHA-256 del payload (opzionale).
        """
        self._write_entry(
            operation="fetch",
            source=source,
            endpoint=endpoint,
            record_count=record_count,
            duration_ms=duration_ms,
            outcome=outcome,
            error_msg=error_msg,
            data_hash_sha256=data_hash,
        )

    @apply_error_policy(
        level="RECOVER",
        fallback=None,
        context="AuditLogger.log_write",
    )
    def log_write(
        self,
        source: str,
        endpoint: str,
        record_count: int = 0,
        duration_ms: float = 0.0,
        outcome: str = _OUTCOME_OK,
        error_msg: str | None = None,
        data_hash: str | None = None,
    ) -> None:
        """Registra un evento di scrittura nel DB.

        Args:
            source: Modulo o processo che ha scritto (es. "vintage_manager").
            endpoint: Tabella o descrizione target (es. "data_vintages/ICSA").
            record_count: Numero di righe scritte.
            duration_ms: Durata dell'operazione in millisecondi.
            outcome: Esito ("ok", "error", "partial").
            error_msg: Messaggio di errore se outcome != "ok".
            data_hash: SHA-256 del contenuto scritto (opzionale).
        """
        self._write_entry(
            operation="write",
            source=source,
            endpoint=endpoint,
            record_count=record_count,
            duration_ms=duration_ms,
            outcome=outcome,
            error_msg=error_msg,
            data_hash_sha256=data_hash,
        )

    @apply_error_policy(
        level="RECOVER",
        fallback=None,
        context="AuditLogger.log_event",
    )
    def log_event(
        self,
        operation: str,
        source: str,
        endpoint: str,
        record_count: int = 0,
        duration_ms: float = 0.0,
        outcome: str = _OUTCOME_OK,
        error_msg: str | None = None,
        data_hash: str | None = None,
    ) -> None:
        """Registra un evento generico nel log di audit.

        Args:
            operation: Tipo di operazione (es. "migration", "validation").
            source: Origine dell'evento.
            endpoint: Target o descrizione.
            record_count: Numero di record coinvolti.
            duration_ms: Durata in millisecondi.
            outcome: Esito ("ok", "error", "partial").
            error_msg: Dettaglio errore.
            data_hash: Hash SHA-256 del dato (opzionale).
        """
        self._write_entry(
            operation=operation,
            source=source,
            endpoint=endpoint,
            record_count=record_count,
            duration_ms=duration_ms,
            outcome=outcome,
            error_msg=error_msg,
            data_hash_sha256=data_hash,
        )

    # ─── Read operations ─────────────────────────────────────────────────

    @apply_error_policy(
        level="DEGRADE",
        fallback=pd.DataFrame(),
        context="AuditLogger.get_recent",
    )
    def get_recent(self, hours: int = 24) -> pd.DataFrame:
        """Restituisce le entry di audit delle ultime N ore.

        Args:
            hours: Finestra temporale in ore (default 24).

        Returns:
            DataFrame con le colonne della tabella audit_log,
            ordinato per event_ts decrescente (più recente prima).
        """
        sql = f"""
            SELECT
                log_id,
                event_ts,
                operation,
                source,
                endpoint,
                data_hash_sha256,
                record_count,
                outcome,
                error_msg,
                duration_ms
            FROM {_TABLE}
            WHERE event_ts >= NOW() - INTERVAL '{hours} hours'
            ORDER BY event_ts DESC
        """
        return self._client.query_df(sql)

    @apply_error_policy(
        level="DEGRADE",
        fallback=pd.DataFrame(),
        context="AuditLogger.get_by_source",
    )
    def get_by_source(
        self,
        source: str,
        limit: int = 100,
    ) -> pd.DataFrame:
        """Restituisce le ultime N entry per un source specifico.

        Args:
            source: Provider da filtrare (es. "fred").
            limit: Numero massimo di righe.

        Returns:
            DataFrame ordinato per event_ts decrescente.
        """
        return self._client.query_df(
            f"""
            SELECT *
            FROM {_TABLE}
            WHERE source = ?
            ORDER BY event_ts DESC
            LIMIT {int(limit)}
            """,
            [source],
        )

    @apply_error_policy(
        level="DEGRADE",
        fallback={"total": 0, "ok": 0, "error": 0, "partial": 0},
        context="AuditLogger.summary",
    )
    def summary(self, hours: int = 24) -> dict[str, int]:
        """Restituisce un riepilogo degli eventi nelle ultime N ore.

        Args:
            hours: Finestra temporale.

        Returns:
            Dict con chiavi: total, ok, error, partial.
        """
        rows = self._client.query(
            f"""
            SELECT outcome, COUNT(*) AS n
            FROM {_TABLE}
            WHERE event_ts >= NOW() - INTERVAL '{hours} hours'
            GROUP BY outcome
            """,
        )
        result: dict[str, int] = {"total": 0, "ok": 0, "error": 0, "partial": 0}
        for outcome, count in rows:
            key = str(outcome).lower() if outcome else "error"
            if key in result:
                result[key] = int(count)
            result["total"] += int(count)
        return result

    # ─── Private helpers ─────────────────────────────────────────────────

    def _write_entry(
        self,
        *,
        operation: str,
        source: str,
        endpoint: str,
        record_count: int,
        duration_ms: float,
        outcome: str,
        error_msg: str | None,
        data_hash_sha256: str | None,
    ) -> None:
        """Scrive una singola riga nella tabella audit_log."""
        now_utc = datetime.now(tz=timezone.utc)

        self._client.execute(
            f"""
            INSERT INTO {_TABLE}
                (event_ts, operation, source, endpoint,
                 data_hash_sha256, record_count, outcome, error_msg, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                now_utc,
                operation,
                source,
                endpoint,
                data_hash_sha256,
                int(record_count),
                outcome,
                error_msg,
                float(duration_ms),
            ],
        )
        log.debug(
            "audit_logger.entry",
            operation=operation,
            source=source,
            endpoint=endpoint,
            outcome=outcome,
            record_count=record_count,
        )


# ─── Utility ─────────────────────────────────────────────────────────────────

def compute_sha256(data: bytes | str) -> str:
    """Calcola l'hash SHA-256 di un payload per l'audit trail.

    Args:
        data: Payload come bytes o stringa UTF-8.

    Returns:
        Stringa esadecimale SHA-256.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()
