#!/usr/bin/env python3
"""DuckDB data retention enforcement (Rule 31).

Deletes data older than the retention policy defined in
``config/data_retention.yaml``. Runs monthly via scheduler.

Usage:
    python scripts/duckdb_retention.py
    make retention
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared.constants import DATA_RETENTION_PATH  # noqa: E402
from shared.db.duckdb_client import get_duckdb_client  # noqa: E402
from shared.logger import configure_logging, get_logger  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════════
# Mapping tabella → colonna timestamp da usare per la retention
# ═══════════════════════════════════════════════════════════════════════════
# Ogni tabella DuckDB ha una colonna timestamp con cui filtrare righe vecchie.
# Questo mapping è esplicito: non deriva da introspezione per evitare errori.
_TABLE_TS_COLUMN: dict[str, str] = {
    "prices_ohlcv": "ts",
    "macro_series": "ts",
    "fundamentals": "period_end",
    "sentiment": "ts",
    "sentiment_observations": "ts",
    "data_quality_reports": "evaluated_at",
    "quality_reports": "evaluated_at",
    "backtest_results": "run_at",
    "stress_scenarios": "generated_at",
    "correlations": "ts",
}


def _load_retention_config(path: Path = DATA_RETENTION_PATH) -> dict[str, int]:
    """Load DuckDB retention config. Values in years."""
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw.get("duckdb", {}) or {}


def main() -> int:
    configure_logging()
    log = get_logger("retention_script")

    config = _load_retention_config()
    if not config:
        log.warning("retention.no_config")
        print("No retention config found — nothing to do.")
        return 0

    client = get_duckdb_client()
    existing_tables = set(client.list_tables())
    now_utc = datetime.now(UTC)

    total_deleted = 0
    for table_key, years in config.items():
        # Il config può usare un alias non esattamente uguale al nome tabella
        table_name = table_key if table_key in existing_tables else _resolve_table(
            table_key, existing_tables
        )
        if table_name is None:
            log.info("retention.table_skipped", table=table_key, reason="not_found")
            continue

        ts_col = _TABLE_TS_COLUMN.get(table_name) or _TABLE_TS_COLUMN.get(table_key)
        if ts_col is None:
            log.warning("retention.no_ts_column", table=table_name)
            continue

        cutoff = now_utc - timedelta(days=int(years) * 365)
        deleted = _delete_older_than(client, table_name, ts_col, cutoff)
        total_deleted += deleted
        log.info(
            "retention.table_cleaned",
            table=table_name,
            cutoff=cutoff.isoformat(),
            deleted_rows=deleted,
        )

    print(f"✓ Retention complete: {total_deleted} rows deleted across all tables.")
    return 0


def _resolve_table(alias: str, existing: set[str]) -> str | None:
    """Attempt to resolve a config key to an actual table name."""
    # Alias noti del config al nome tabella effettivo
    aliases = {
        "sentiment": "sentiment_observations",
        "quality_reports": "data_quality_reports",
    }
    resolved = aliases.get(alias, alias)
    return resolved if resolved in existing else None


def _delete_older_than(client: object, table: str, ts_col: str, cutoff: datetime) -> int:
    """Delete rows from ``table`` where ``ts_col < cutoff``. Returns row count."""
    # Count prima di cancellare, per sapere quante righe sono state eliminate
    count_sql = f"SELECT COUNT(*) FROM {table} WHERE {ts_col} < ?"
    rows = client.query(count_sql, [cutoff])  # type: ignore[attr-defined]
    count = rows[0][0] if rows else 0
    if count == 0:
        return 0
    delete_sql = f"DELETE FROM {table} WHERE {ts_col} < ?"
    client.execute(delete_sql, [cutoff])  # type: ignore[attr-defined]
    return int(count)


if __name__ == "__main__":
    sys.exit(main())
