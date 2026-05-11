"""Stress scenarios repository — persists ``StressScenario`` to DuckDB.

Schema lives in the initial DuckDB migration (table ``stress_scenarios``).
Each row stores one scenario with its calibration metadata. Read methods
support filtering by type / age for dashboards and alert engines.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from shared.db.duckdb_client import DuckDBClient, get_duckdb_client
from shared.exceptions import DuckDBError
from shared.logger import get_logger
from shared.metrics import metrics
from shared.types import ensure_utc

if TYPE_CHECKING:
    from datetime import datetime

    from engine.stress_testing.scenario import StressScenario

__version__ = "6.0.0"

__all__ = ["StressScenariosRepository", "get_stress_scenarios_repo"]

log = get_logger(__name__)

_TABLE = "stress_scenarios"


class StressScenariosRepository:
    """Persistence layer for stress scenarios."""

    def __init__(self, client: DuckDBClient | None = None) -> None:
        self._client = client or get_duckdb_client()

    # ─── Writes ──────────────────────────────────────────────────────────
    def write(self, scenario: StressScenario) -> None:
        """Persist a single scenario row.

        Idempotent on (scenario_id) primary key — rerun replaces existing row.
        """
        payload = scenario.to_persistence_dict()
        with metrics.timer("stress_scenarios_write_ms"):
            try:
                self._client.execute(
                    f"""
                    INSERT OR REPLACE INTO {_TABLE} (
                        scenario_id, scenario_type, name, description,
                        equity_shock_pct, bond_shock_pct, fx_shock_pct,
                        vol_multiplier, probability, generated_at, market_context
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        payload["scenario_id"],
                        payload["scenario_type"],
                        payload["name"],
                        payload["description"],
                        payload["equity_shock_pct"],
                        payload["bond_shock_pct"],
                        payload["fx_shock_pct"],
                        payload["vol_multiplier"],
                        payload["probability"],
                        payload["generated_at"],
                        payload["market_context"],
                    ],
                )
            except DuckDBError as exc:
                log.error("stress_scenario.write_failed",
                          scenario_id=payload["scenario_id"], error=str(exc))
                raise

        metrics.inc("stress_scenarios_written_total",
                    scenario_type=str(payload["scenario_type"]))
        log.info(
            "stress_scenario.written",
            scenario_id=payload["scenario_id"],
            name=payload["name"],
        )

    def write_many(self, scenarios: list[StressScenario]) -> int:
        """Persist multiple scenarios. Returns the count written."""
        for scenario in scenarios:
            self.write(scenario)
        return len(scenarios)

    # ─── Reads ───────────────────────────────────────────────────────────
    def read_recent(
        self,
        scenario_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        """Fetch most recent scenarios as dicts.

        Args:
            scenario_type: Optional filter ('historical' or 'synthetic').
            limit: Max rows returned.

        Returns:
            List of dicts (column_name -> value). Empty list if no matches.
        """
        if scenario_type is not None:
            rows = self._client.query(
                f"""
                SELECT scenario_id, scenario_type, name, description,
                       equity_shock_pct, bond_shock_pct, fx_shock_pct,
                       vol_multiplier, probability, generated_at, market_context
                FROM {_TABLE}
                WHERE scenario_type = ?
                ORDER BY generated_at DESC
                LIMIT ?
                """,
                [scenario_type, limit],
            )
        else:
            rows = self._client.query(
                f"""
                SELECT scenario_id, scenario_type, name, description,
                       equity_shock_pct, bond_shock_pct, fx_shock_pct,
                       vol_multiplier, probability, generated_at, market_context
                FROM {_TABLE}
                ORDER BY generated_at DESC
                LIMIT ?
                """,
                [limit],
            )

        cols = [
            "scenario_id", "scenario_type", "name", "description",
            "equity_shock_pct", "bond_shock_pct", "fx_shock_pct",
            "vol_multiplier", "probability", "generated_at", "market_context",
        ]
        return [dict(zip(cols, row, strict=True)) for row in rows]

    def count(self, scenario_type: str | None = None) -> int:
        """Count persisted scenarios, optionally filtered by type."""
        if scenario_type is not None:
            rows = self._client.query(
                f"SELECT COUNT(*) FROM {_TABLE} WHERE scenario_type = ?",
                [scenario_type],
            )
        else:
            rows = self._client.query(f"SELECT COUNT(*) FROM {_TABLE}")
        return int(rows[0][0]) if rows else 0

    def delete_older_than(self, before_ts: datetime) -> int:
        """Retention helper — remove scenarios older than ``before_ts``.

        Returns the number of rows deleted.
        """
        cutoff = ensure_utc(before_ts)
        count_rows = self._client.query(
            f"SELECT COUNT(*) FROM {_TABLE} WHERE generated_at < ?", [cutoff]
        )
        n = int(count_rows[0][0]) if count_rows else 0
        if n > 0:
            self._client.execute(
                f"DELETE FROM {_TABLE} WHERE generated_at < ?", [cutoff]
            )
            log.info("stress_scenarios.retention_cleanup", rows=n)
        return n


# ═══════════════════════════════════════════════════════════════════════════
# Singleton accessor
# ═══════════════════════════════════════════════════════════════════════════
_INSTANCE: StressScenariosRepository | None = None


def get_stress_scenarios_repo() -> StressScenariosRepository:
    """Return the process-wide StressScenariosRepository singleton."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = StressScenariosRepository()
    return _INSTANCE


def reset_stress_scenarios_repo() -> None:
    """Reset the singleton (tests only)."""
    global _INSTANCE
    _INSTANCE = None
