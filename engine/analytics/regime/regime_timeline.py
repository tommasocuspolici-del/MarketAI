"""RegimeTimelineRepo — lettura/scrittura macro_regime_timeline in DuckDB."""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

import pandas as pd

from shared.logger import get_logger

if TYPE_CHECKING:
    from engine.analytics.regime.hmm_macro_regime import RegimeOutput
    from shared.db.duckdb_client import DuckDBClient

log = get_logger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS macro_regime_timeline (
    snapshot_date    DATE    NOT NULL PRIMARY KEY,
    regime_label     VARCHAR NOT NULL,
    prob_expansion   DOUBLE  NOT NULL,
    prob_slowdown    DOUBLE  NOT NULL,
    prob_contraction DOUBLE  NOT NULL,
    prob_recovery    DOUBLE  NOT NULL,
    confidence       DOUBLE  NOT NULL,
    model_version    VARCHAR NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL
)
"""

_UPSERT_SQL = """
INSERT INTO macro_regime_timeline (
    snapshot_date, regime_label,
    prob_expansion, prob_slowdown, prob_contraction, prob_recovery,
    confidence, model_version, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (snapshot_date) DO UPDATE SET
    regime_label     = excluded.regime_label,
    prob_expansion   = excluded.prob_expansion,
    prob_slowdown    = excluded.prob_slowdown,
    prob_contraction = excluded.prob_contraction,
    prob_recovery    = excluded.prob_recovery,
    confidence       = excluded.confidence,
    model_version    = excluded.model_version,
    created_at       = excluded.created_at
"""


class RegimeTimelineRepo:
    """Repository per la persistenza del macro regime timeline in DuckDB."""

    TABLE = "macro_regime_timeline"

    def __init__(self, db: DuckDBClient) -> None:
        self._db = db
        self._ensure_table()

    def _ensure_table(self) -> None:
        try:
            self._db.execute(_CREATE_TABLE_SQL)
        except Exception as exc:
            log.warning("regime_timeline.table_create_failed", error=str(exc))

    def persist(self, output: RegimeOutput, snapshot_date: date) -> None:
        """Salva o aggiorna un RegimeOutput in DuckDB.

        Args:
            output: RegimeOutput con probabilità e regime corrente.
            snapshot_date: Data della snapshot.
        """
        now = datetime.now(UTC)
        try:
            self._db.execute(
                _UPSERT_SQL,
                [
                    snapshot_date,
                    output.current_regime.value,
                    output.prob_expansion,
                    output.prob_slowdown,
                    output.prob_contraction,
                    output.prob_recovery,
                    output.confidence,
                    output.model_version,
                    now,
                ],
            )
            log.info(
                "regime_timeline.persisted",
                snapshot_date=str(snapshot_date),
                regime=output.current_regime.value,
                confidence=round(output.confidence, 3),
            )
        except Exception as exc:
            log.error("regime_timeline.persist_failed", error=str(exc))
            raise

    def get_history(self, days: int = 365) -> pd.DataFrame:
        """Restituisce la storia del regime degli ultimi N giorni.

        Args:
            days: Numero di giorni da includere.

        Returns:
            DataFrame ordinato per snapshot_date DESC.
        """
        sql = """
            SELECT * FROM macro_regime_timeline
            WHERE snapshot_date >= CURRENT_DATE - INTERVAL ? DAY
            ORDER BY snapshot_date DESC
        """
        try:
            return self._db.query_df(sql, [days])
        except Exception as exc:
            log.error("regime_timeline.get_history_failed", error=str(exc))
            return pd.DataFrame()

    def get_current(self) -> pd.DataFrame | None:
        """Restituisce la snapshot più recente.

        Returns:
            DataFrame con una riga (la più recente), o None se la tabella è vuota.
        """
        sql = """
            SELECT * FROM macro_regime_timeline
            ORDER BY snapshot_date DESC
            LIMIT 1
        """
        try:
            df = self._db.query_df(sql)
            return df if len(df) > 0 else None
        except Exception as exc:
            log.error("regime_timeline.get_current_failed", error=str(exc))
            return None

    def get_regime_stats(self) -> pd.DataFrame:
        """Restituisce la distribuzione storica dei regimi (conteggi e percentuali).

        Returns:
            DataFrame con colonne: regime_label, count, pct.
        """
        sql = """
            SELECT
                regime_label,
                COUNT(*) AS count,
                ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
            FROM macro_regime_timeline
            GROUP BY regime_label
            ORDER BY count DESC
        """
        try:
            return self._db.query_df(sql)
        except Exception as exc:
            log.error("regime_timeline.get_regime_stats_failed", error=str(exc))
            return pd.DataFrame()
