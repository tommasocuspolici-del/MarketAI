"""Signal Scorecard — Convenzione 37. Persistita in DuckDB signal_scorecard."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

import pandas as pd

from engine.analytics.signals.ic_calculator import ICResult
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

log = get_logger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS signal_scorecard (
    signal_id        VARCHAR NOT NULL,
    snapshot_date    DATE    NOT NULL,
    horizon_days     INTEGER NOT NULL,
    ic_mean          DOUBLE  NOT NULL,
    ic_std           DOUBLE  NOT NULL,
    ic_tstat         DOUBLE  NOT NULL,
    ic_ir            DOUBLE  NOT NULL,
    hit_rate         DOUBLE  NOT NULL,
    sharpe_ls        DOUBLE  NOT NULL DEFAULT 0.0,
    alpha_decay_hl   INTEGER NOT NULL DEFAULT 0,
    is_stale         BOOLEAN NOT NULL DEFAULT FALSE,
    staleness_days   INTEGER NOT NULL DEFAULT 0,
    is_significant   BOOLEAN NOT NULL DEFAULT FALSE,
    weight_current   DOUBLE  NOT NULL DEFAULT 0.0,
    created_at       TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (signal_id, snapshot_date, horizon_days)
)
"""

_UPSERT_SQL = """
INSERT INTO signal_scorecard (
    signal_id, snapshot_date, horizon_days,
    ic_mean, ic_std, ic_tstat, ic_ir, hit_rate,
    sharpe_ls, alpha_decay_hl, is_stale, staleness_days,
    is_significant, weight_current, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (signal_id, snapshot_date, horizon_days) DO UPDATE SET
    ic_mean        = excluded.ic_mean,
    ic_std         = excluded.ic_std,
    ic_tstat       = excluded.ic_tstat,
    ic_ir          = excluded.ic_ir,
    hit_rate       = excluded.hit_rate,
    sharpe_ls      = excluded.sharpe_ls,
    alpha_decay_hl = excluded.alpha_decay_hl,
    is_stale       = excluded.is_stale,
    staleness_days = excluded.staleness_days,
    is_significant = excluded.is_significant,
    weight_current = excluded.weight_current,
    created_at     = excluded.created_at
"""


@dataclass
class ScorecardEntry:
    signal_id: str
    snapshot_date: date
    horizon_days: int
    ic_mean: float
    ic_std: float
    ic_tstat: float
    ic_ir: float
    hit_rate: float
    sharpe_ls: float
    alpha_decay_hl: int       # half-life in days
    is_stale: bool
    staleness_days: int
    is_significant: bool
    weight_current: float


class SignalScorecard:
    """Persiste e recupera Signal Scorecard da DuckDB."""

    TABLE = "signal_scorecard"

    def __init__(self, db: DuckDBClient) -> None:
        self._db = db
        self._ensure_table()

    def _ensure_table(self) -> None:
        try:
            self._db.execute(_CREATE_TABLE_SQL)
        except Exception as exc:
            log.warning("signal_scorecard.table_create_failed", error=str(exc))

    def persist(self, entry: ScorecardEntry) -> None:
        """Salva o aggiorna una ScorecardEntry in DuckDB."""
        now = datetime.now(UTC)
        try:
            self._db.execute(
                _UPSERT_SQL,
                [
                    entry.signal_id,
                    entry.snapshot_date,
                    entry.horizon_days,
                    entry.ic_mean,
                    entry.ic_std,
                    entry.ic_tstat,
                    entry.ic_ir,
                    entry.hit_rate,
                    entry.sharpe_ls,
                    entry.alpha_decay_hl,
                    entry.is_stale,
                    entry.staleness_days,
                    entry.is_significant,
                    entry.weight_current,
                    now,
                ],
            )
            log.info("signal_scorecard.persisted", signal_id=entry.signal_id, snapshot_date=str(entry.snapshot_date))
        except Exception as exc:
            log.error("signal_scorecard.persist_failed", signal_id=entry.signal_id, error=str(exc))
            raise

    def persist_from_ic(
        self,
        ic_result: ICResult,
        snapshot_date: date,
        sharpe_ls: float = 0.0,
        alpha_decay_hl: int = 0,
        is_stale: bool = False,
        staleness_days: int = 0,
        weight_current: float = 0.0,
    ) -> None:
        """Convenience: costruisce ScorecardEntry da ICResult e persiste."""
        entry = ScorecardEntry(
            signal_id=ic_result.signal_id,
            snapshot_date=snapshot_date,
            horizon_days=ic_result.horizon_days,
            ic_mean=ic_result.ic_mean,
            ic_std=ic_result.ic_std,
            ic_tstat=ic_result.ic_tstat,
            ic_ir=ic_result.ic_ir,
            hit_rate=ic_result.hit_rate,
            sharpe_ls=sharpe_ls,
            alpha_decay_hl=alpha_decay_hl,
            is_stale=is_stale,
            staleness_days=staleness_days,
            is_significant=ic_result.is_significant,
            weight_current=weight_current,
        )
        self.persist(entry)

    def get_latest(self, signal_id: str | None = None) -> pd.DataFrame:
        """Restituisce l'ultima snapshot per ogni (signal_id, horizon_days).

        Args:
            signal_id: Se specificato, filtra per questo signal_id.

        Returns:
            DataFrame con le colonne di signal_scorecard.
        """
        if signal_id:
            sql = """
                SELECT * FROM signal_scorecard s
                WHERE signal_id = ?
                  AND snapshot_date = (
                      SELECT MAX(snapshot_date) FROM signal_scorecard s2
                      WHERE s2.signal_id = s.signal_id
                        AND s2.horizon_days = s.horizon_days
                  )
                ORDER BY horizon_days
            """
            params: list[Any] = [signal_id]
        else:
            sql = """
                SELECT * FROM signal_scorecard s
                WHERE snapshot_date = (
                    SELECT MAX(snapshot_date) FROM signal_scorecard s2
                    WHERE s2.signal_id = s.signal_id
                      AND s2.horizon_days = s.horizon_days
                )
                ORDER BY signal_id, horizon_days
            """
            params = []
        try:
            return self._db.query_df(sql, params if params else None)
        except Exception as exc:
            log.error("signal_scorecard.get_latest_failed", error=str(exc))
            return pd.DataFrame()

    def get_history(self, signal_id: str, days: int = 90) -> pd.DataFrame:
        """Restituisce la storia di un segnale negli ultimi N giorni."""
        sql = """
            SELECT * FROM signal_scorecard
            WHERE signal_id = ?
              AND snapshot_date >= CURRENT_DATE - INTERVAL ? DAY
            ORDER BY snapshot_date DESC, horizon_days
        """
        try:
            return self._db.query_df(sql, [signal_id, days])
        except Exception as exc:
            log.error("signal_scorecard.get_history_failed", signal_id=signal_id, error=str(exc))
            return pd.DataFrame()

    def get_active_signals(self) -> list[str]:
        """Restituisce i signal_id con is_significant=True nella snapshot più recente."""
        sql = """
            SELECT DISTINCT signal_id FROM signal_scorecard
            WHERE is_significant = TRUE
              AND snapshot_date = (SELECT MAX(snapshot_date) FROM signal_scorecard)
        """
        try:
            rows = self._db.query(sql)
            return [row[0] for row in rows]
        except Exception as exc:
            log.error("signal_scorecard.get_active_failed", error=str(exc))
            return []

    def get_stale_signals(self) -> list[str]:
        """Restituisce i signal_id con is_stale=True nella snapshot più recente."""
        sql = """
            SELECT DISTINCT signal_id FROM signal_scorecard
            WHERE is_stale = TRUE
              AND snapshot_date = (SELECT MAX(snapshot_date) FROM signal_scorecard)
        """
        try:
            rows = self._db.query(sql)
            return [row[0] for row in rows]
        except Exception as exc:
            log.error("signal_scorecard.get_stale_failed", error=str(exc))
            return []
