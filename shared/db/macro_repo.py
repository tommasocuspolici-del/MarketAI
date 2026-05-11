"""Macro series repository — macro_series table specialized access.

Single-responsibility module (Rule 2): FRED, ECB, BLS, World Bank, IMF
macro data reads/writes live here. Upserts by (series_id, ts).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from shared.db.duckdb_client import DuckDBClient, get_duckdb_client
from shared.db.schemas import validate_macro_series
from shared.exceptions import DuckDBError
from shared.logger import get_logger
from shared.metrics import metrics
from shared.types import ensure_utc

if TYPE_CHECKING:
    from datetime import datetime

__version__ = "6.0.0"

__all__ = ["MacroRepository", "get_macro_repository"]

log = get_logger(__name__)

_TABLE = "macro_series"


class MacroRepository:
    """Specialized access to macro time-series on DuckDB."""

    def __init__(self, client: DuckDBClient | None = None) -> None:
        self._client = client or get_duckdb_client()

    # ─── Writes ──────────────────────────────────────────────────────────
    def write_macro_series(
        self,
        series_id: str,
        df: pd.DataFrame,
        source: str,
        unit: str | None = None,
        frequency: str | None = None,
    ) -> int:
        """Insert or replace macro observations for a series.

        Args:
            series_id: Provider-specific id (e.g. "GDP", "UNRATE").
            df: DataFrame with columns ``ts``, ``value`` (validated against
                MACRO_SERIES_SCHEMA).
            source: Provider identifier (e.g. "fred", "ecb").
            unit: Optional unit of measurement (e.g. "Percent", "USD").
            frequency: Optional release frequency ("D", "W", "M", "Q", "Y").

        Returns:
            Number of rows upserted.
        """
        if df.empty:
            return 0

        # Regola 9: ogni DataFrame validato da Pandera prima del write
        validated = validate_macro_series(df)
        prepared = self._prepare_for_insert(
            validated, series_id, source, unit, frequency
        )
        n_rows = len(prepared)

        with metrics.timer("duckdb_write_macro_ms", source=source):
            try:
                self._client.connection.register("__macro_stage__", prepared)
                # Upsert idempotente sulla PK (series_id, ts)
                self._client.execute(
                    f"""
                    INSERT OR REPLACE INTO {_TABLE}
                    SELECT series_id, ts, value, source, unit, frequency, inserted_at
                    FROM __macro_stage__
                    """
                )
                self._client.connection.unregister("__macro_stage__")
            except DuckDBError:
                import contextlib

                with contextlib.suppress(Exception):
                    self._client.connection.unregister("__macro_stage__")
                raise

        metrics.inc("macro_rows_written_total", amount=n_rows, source=source)
        log.info(
            "macro.written",
            series_id=series_id,
            rows=n_rows,
            source=source,
            unit=unit,
            frequency=frequency,
        )
        return n_rows

    @staticmethod
    def _prepare_for_insert(
        df: pd.DataFrame,
        series_id: str,
        source: str,
        unit: str | None,
        frequency: str | None,
    ) -> pd.DataFrame:
        """Build the column set matching the macro_series table."""
        out = df.copy()
        out["series_id"] = series_id
        out["source"] = source
        out["unit"] = unit
        out["frequency"] = frequency
        out["inserted_at"] = pd.Timestamp.now(tz="UTC")

        column_order = [
            "series_id",
            "ts",
            "value",
            "source",
            "unit",
            "frequency",
            "inserted_at",
        ]
        return out[column_order]

    # ─── Reads ───────────────────────────────────────────────────────────
    def read_macro(
        self,
        series_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """Fetch a macro series with optional date filters.

        Returns DataFrame with columns: ts (UTC), value, unit, frequency.
        Empty DataFrame when no rows match.
        """
        clauses = ["series_id = ?"]
        params: list[object] = [series_id]
        if start is not None:
            clauses.append("ts >= ?")
            params.append(ensure_utc(start))
        if end is not None:
            clauses.append("ts <= ?")
            params.append(ensure_utc(end))

        where = " AND ".join(clauses)
        sql = (
            f"SELECT ts, value, unit, frequency, source "
            f"FROM {_TABLE} WHERE {where} ORDER BY ts"
        )
        with metrics.timer("duckdb_read_macro_ms"):
            return self._client.query_df(sql, params)

    def read_latest_macro(self, series_id: str) -> dict[str, object] | None:
        """Return the most recent observation for a macro series, or None."""
        sql = (
            f"SELECT series_id, ts, value, unit, frequency, source "
            f"FROM {_TABLE} WHERE series_id = ? ORDER BY ts DESC LIMIT 1"
        )
        rows = self._client.query(sql, [series_id])
        if not rows:
            return None
        cols = ["series_id", "ts", "value", "unit", "frequency", "source"]
        return dict(zip(cols, rows[0], strict=True))

    def list_series(self, source: str | None = None) -> list[str]:
        """Return distinct series_ids, optionally filtered by source."""
        if source is None:
            rows = self._client.query(
                f"SELECT DISTINCT series_id FROM {_TABLE} ORDER BY series_id"
            )
        else:
            rows = self._client.query(
                f"SELECT DISTINCT series_id FROM {_TABLE} "
                f"WHERE source = ? ORDER BY series_id",
                [source],
            )
        return [r[0] for r in rows]

    def count_observations(self, series_id: str) -> int:
        """Count observations persisted for a series."""
        rows = self._client.query(
            f"SELECT COUNT(*) FROM {_TABLE} WHERE series_id = ?", [series_id]
        )
        return int(rows[0][0]) if rows else 0


# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════
_INSTANCE: MacroRepository | None = None


def get_macro_repository() -> MacroRepository:
    """Return the process-wide MacroRepository singleton."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = MacroRepository()
    return _INSTANCE


def reset_macro_repository() -> None:
    """Reset the singleton (tests only)."""
    global _INSTANCE
    _INSTANCE = None
