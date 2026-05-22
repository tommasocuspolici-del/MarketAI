"""Vintage Manager — gestione storico revisioni per le serie macro.

Permette di:
  - Registrare ogni pubblicazione/revisione di un dato (data_vintages)
  - Ricostruire il dataset "as-of" una certa data (point-in-time)
  - Analizzare la magnitudine delle revisioni

Regola 12: solo letture/scritture DuckDB qui; nessuna API fetch.
Regola 19: tutti i datetime UTC-aware.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any

import pandas as pd

from shared.logger import get_logger
from shared.resilience.error_policy import ErrorLevel, apply_error_policy, error_policy

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["VintageManager"]

log = get_logger(__name__)

_TABLE = "data_vintages"


class VintageManager:
    """Gestisce la tabella data_vintages per il tracking point-in-time.

    Args:
        client: DuckDBClient per le operazioni sul DB.

    Esempio::

        from shared.db.duckdb_client import get_duckdb_client
        from engine.data_universe.vintage_manager import VintageManager

        vm = VintageManager(client=get_duckdb_client())
        vm.record_vintage("ICSA", date(2024, 1, 5), date(2024, 1, 6), 215000.0, "fred")
        df = vm.get_as_of("ICSA", date(2024, 6, 1))
    """

    def __init__(self, client: DuckDBClient) -> None:
        self._client = client

    # ─── Write operations ────────────────────────────────────────────────

    @apply_error_policy(
        level="DEGRADE",
        fallback=0,
        context="VintageManager.record_vintage",
    )
    def record_vintage(
        self,
        series_id: str,
        observation_date: date,
        vintage_date: date,
        value: float,
        source: str = "fred",
        *,
        first_published: date | None = None,
    ) -> int:
        """Registra un'osservazione con il suo vintage (data di prima pubblicazione/revisione).

        Se la coppia (series_id, observation_date, vintage_date) esiste già,
        l'operazione è ignorata (INSERT OR IGNORE semantics via DO NOTHING).

        Args:
            series_id: Codice serie (es. "ICSA").
            observation_date: Data a cui si riferisce il dato.
            vintage_date: Data in cui il dato è stato pubblicato/rivisto.
            value: Valore numerico osservato.
            source: Provider dei dati (default "fred").
            first_published: Prima data di pubblicazione (per tracciare revisioni).

        Returns:
            1 se inserito, 0 se già presente.
        """
        # Verifica se è una revisione rispetto al vintage precedente
        is_revised, revision_count = self._check_revision(series_id, observation_date, value)
        fp = first_published or vintage_date

        self._client.execute(
            f"""
            INSERT INTO {_TABLE}
                (series_id, observation_date, vintage_date, value,
                 is_revised, revision_count, first_published, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (series_id, observation_date, vintage_date) DO NOTHING
            """,
            [
                series_id,
                observation_date,
                vintage_date,
                float(value),
                is_revised,
                revision_count,
                fp,
                source,
            ],
        )
        log.debug(
            "vintage_manager.record",
            series_id=series_id,
            observation_date=str(observation_date),
            vintage_date=str(vintage_date),
            is_revised=is_revised,
        )
        return 1

    def bulk_record(
        self,
        series_id: str,
        df: pd.DataFrame,
        vintage_date: date,
        source: str = "fred",
    ) -> int:
        """Inserisce un batch di osservazioni per un dato vintage.

        Args:
            series_id: Codice serie.
            df: DataFrame con colonne 'observation_date' (date) e 'value' (float).
            vintage_date: Data di pubblicazione del vintage.
            source: Provider dei dati.

        Returns:
            Numero di righe inserite.
        """
        if df.empty:
            return 0

        total = 0
        for _, row in df.iterrows():
            obs_date = _to_date(row["observation_date"])
            if obs_date is None:
                continue
            total += self.record_vintage(
                series_id=series_id,
                observation_date=obs_date,
                vintage_date=vintage_date,
                value=float(row["value"]),
                source=source,
            )
        log.info(
            "vintage_manager.bulk_record",
            series_id=series_id,
            vintage_date=str(vintage_date),
            rows=total,
        )
        return total

    # ─── Read operations ─────────────────────────────────────────────────

    @apply_error_policy(
        level="DEGRADE",
        fallback=pd.DataFrame(),
        context="VintageManager.get_as_of",
    )
    def get_as_of(self, series_id: str, as_of_date: date) -> pd.DataFrame:
        """Restituisce i valori della serie come noti alla data as_of_date.

        Implementa la semantica point-in-time: per ogni observation_date
        viene scelto il vintage più recente che non supera as_of_date.

        Args:
            series_id: Codice serie.
            as_of_date: Data limite per la selezione dei vintage.

        Returns:
            DataFrame con colonne: observation_date, value, vintage_date.
            Ordinato per observation_date crescente.
        """
        sql = f"""
            SELECT
                observation_date,
                value,
                vintage_date,
                is_revised,
                revision_count
            FROM {_TABLE}
            WHERE series_id = ?
              AND vintage_date <= ?
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY observation_date
                ORDER BY vintage_date DESC
            ) = 1
            ORDER BY observation_date ASC
        """
        df = self._client.query_df(sql, [series_id, as_of_date])
        return df

    @apply_error_policy(
        level="DEGRADE",
        fallback=pd.DataFrame(),
        context="VintageManager.detect_revisions",
    )
    def detect_revisions(self, series_id: str) -> pd.DataFrame:
        """Mostra la storia delle revisioni per ogni observation_date.

        Per ogni coppia (observation_date, vintage), calcola la variazione
        rispetto al vintage precedente.

        Args:
            series_id: Codice serie.

        Returns:
            DataFrame con colonne: observation_date, vintage_date, value,
            prev_value, revision_abs, revision_pct.
        """
        sql = f"""
            WITH ranked AS (
                SELECT
                    observation_date,
                    vintage_date,
                    value,
                    LAG(value) OVER (
                        PARTITION BY observation_date
                        ORDER BY vintage_date ASC
                    ) AS prev_value
                FROM {_TABLE}
                WHERE series_id = ?
            )
            SELECT
                observation_date,
                vintage_date,
                value,
                prev_value,
                (value - prev_value)          AS revision_abs,
                CASE
                    WHEN prev_value != 0 AND prev_value IS NOT NULL
                    THEN (value - prev_value) / ABS(prev_value) * 100.0
                    ELSE NULL
                END                           AS revision_pct
            FROM ranked
            WHERE prev_value IS NOT NULL
              AND ABS(value - prev_value) > 1e-10
            ORDER BY observation_date, vintage_date
        """
        return self._client.query_df(sql, [series_id])

    @apply_error_policy(
        level="DEGRADE",
        fallback={},
        context="VintageManager.get_revision_stats",
    )
    def get_revision_stats(self, series_id: str) -> dict[str, Any]:
        """Calcola statistiche aggregate sulle revisioni di una serie.

        Args:
            series_id: Codice serie.

        Returns:
            Dict con chiavi: avg_revision_abs, max_revision_abs,
            avg_revision_pct, total_revisions, series_id.
        """
        sql = f"""
            WITH ranked AS (
                SELECT
                    observation_date,
                    vintage_date,
                    value,
                    LAG(value) OVER (
                        PARTITION BY observation_date
                        ORDER BY vintage_date ASC
                    ) AS prev_value
                FROM {_TABLE}
                WHERE series_id = ?
                  AND is_revised = TRUE
            ),
            diffs AS (
                SELECT
                    ABS(value - prev_value)                              AS abs_diff,
                    CASE
                        WHEN prev_value != 0 AND prev_value IS NOT NULL
                        THEN ABS((value - prev_value) / prev_value * 100.0)
                        ELSE NULL
                    END AS pct_diff
                FROM ranked
                WHERE prev_value IS NOT NULL
            )
            SELECT
                AVG(abs_diff)  AS avg_revision_abs,
                MAX(abs_diff)  AS max_revision_abs,
                AVG(pct_diff)  AS avg_revision_pct,
                COUNT(*)       AS total_revisions
            FROM diffs
        """
        rows = self._client.query(sql, [series_id])
        if not rows or rows[0][0] is None:
            return {
                "series_id": series_id,
                "avg_revision_abs": 0.0,
                "max_revision_abs": 0.0,
                "avg_revision_pct": 0.0,
                "total_revisions": 0,
            }
        row = rows[0]
        return {
            "series_id": series_id,
            "avg_revision_abs": float(row[0] or 0.0),
            "max_revision_abs": float(row[1] or 0.0),
            "avg_revision_pct": float(row[2] or 0.0),
            "total_revisions": int(row[3] or 0),
        }

    # ─── Private helpers ─────────────────────────────────────────────────

    def _check_revision(
        self,
        series_id: str,
        observation_date: date,
        new_value: float,
    ) -> tuple[bool, int]:
        """Controlla se esiste già un vintage per questa observation_date.

        Returns:
            (is_revised, revision_count) — revisione rispetto all'ultimo valore noto.
        """
        rows = self._client.query(
            f"""
            SELECT value, revision_count
            FROM {_TABLE}
            WHERE series_id = ? AND observation_date = ?
            ORDER BY vintage_date DESC
            LIMIT 1
            """,
            [series_id, observation_date],
        )
        if not rows:
            return False, 0
        prev_value, prev_count = rows[0]
        is_revised = abs(float(prev_value) - float(new_value)) > 1e-10
        return is_revised, int(prev_count or 0) + (1 if is_revised else 0)


# ─── Utility ─────────────────────────────────────────────────────────────────

def _to_date(value: Any) -> date | None:
    """Converte un valore (str, datetime, date, pd.Timestamp) in date o None."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None
    return None
