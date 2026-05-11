"""Tests for engine.stress_testing.scenarios_repo."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from engine.stress_testing.historical_scenarios import build_historical_scenarios
from engine.stress_testing.scenario import (
    MarketContext,
    ScenarioType,
    StressScenario,
)
from engine.stress_testing.scenario_generator import ScenarioGenerator
from engine.stress_testing.scenarios_repo import StressScenariosRepository
from shared.constants import MIGRATIONS_DUCKDB_DIR
from shared.db.duckdb_client import DuckDBClient
from shared.db.duckdb_migrator import DuckDBMigrator

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def repo(tmp_duckdb_path: Path) -> StressScenariosRepository:
    """Fresh DuckDB with schema applied + repo bound to it."""
    client = DuckDBClient(path=tmp_duckdb_path)
    DuckDBMigrator(client=client, migrations_dir=MIGRATIONS_DUCKDB_DIR).apply_pending()
    return StressScenariosRepository(client=client)


def _ctx() -> MarketContext:
    return MarketContext(
        vix=20.0, yield_curve_2y_10y=0.0,
        sentiment_composite=0.0, regime="transition",
        timestamp=datetime(2025, 4, 1, tzinfo=UTC),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Writes
# ═══════════════════════════════════════════════════════════════════════════
class TestWrite:
    def test_write_historical_scenario(self, repo: StressScenariosRepository) -> None:
        scenario = build_historical_scenarios()[0]
        repo.write(scenario)
        assert repo.count() == 1
        assert repo.count(scenario_type="historical") == 1
        assert repo.count(scenario_type="synthetic") == 0

    def test_write_synthetic_scenario(self, repo: StressScenariosRepository) -> None:
        synthetic = ScenarioGenerator.generate(_ctx())[0]
        repo.write(synthetic)
        assert repo.count(scenario_type="synthetic") == 1

    def test_write_idempotent_on_id(self, repo: StressScenariosRepository) -> None:
        scenario = build_historical_scenarios()[0]
        repo.write(scenario)
        repo.write(scenario)  # Stesso scenario_id → INSERT OR REPLACE
        assert repo.count() == 1

    def test_write_many(self, repo: StressScenariosRepository) -> None:
        all_scenarios = build_historical_scenarios() + ScenarioGenerator.generate(_ctx())
        n = repo.write_many(all_scenarios)
        assert n == len(all_scenarios)
        assert repo.count() == len(all_scenarios)
        assert repo.count(scenario_type="historical") == 4
        assert repo.count(scenario_type="synthetic") >= 5


# ═══════════════════════════════════════════════════════════════════════════
# Reads
# ═══════════════════════════════════════════════════════════════════════════
class TestRead:
    def test_read_recent_returns_dicts(self, repo: StressScenariosRepository) -> None:
        scenario = build_historical_scenarios()[0]
        repo.write(scenario)
        rows = repo.read_recent()
        assert len(rows) == 1
        assert rows[0]["name"] == scenario.name
        assert rows[0]["scenario_type"] == "historical"

    def test_read_filtered_by_type(self, repo: StressScenariosRepository) -> None:
        repo.write_many(build_historical_scenarios())
        repo.write_many(ScenarioGenerator.generate(_ctx()))

        historical = repo.read_recent(scenario_type="historical")
        synthetic = repo.read_recent(scenario_type="synthetic")
        assert all(r["scenario_type"] == "historical" for r in historical)
        assert all(r["scenario_type"] == "synthetic" for r in synthetic)

    def test_read_recent_limit(self, repo: StressScenariosRepository) -> None:
        repo.write_many(build_historical_scenarios())
        rows = repo.read_recent(limit=2)
        assert len(rows) == 2

    def test_read_empty_returns_empty(self, repo: StressScenariosRepository) -> None:
        assert repo.read_recent() == []
        assert repo.count() == 0


# ═══════════════════════════════════════════════════════════════════════════
# Retention
# ═══════════════════════════════════════════════════════════════════════════
class TestRetention:
    def test_delete_older_than(self, repo: StressScenariosRepository) -> None:
        # Crea scenario "vecchio" e uno "recente"
        old_scenario = StressScenario(
            name="Old",
            scenario_type=ScenarioType.HISTORICAL,
            equity_shock_pct=-0.1, bond_shock_pct=0.0,
            generated_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        recent_scenario = StressScenario(
            name="Recent",
            scenario_type=ScenarioType.HISTORICAL,
            equity_shock_pct=-0.1, bond_shock_pct=0.0,
            generated_at=datetime(2025, 4, 1, tzinfo=UTC),
        )
        repo.write(old_scenario)
        repo.write(recent_scenario)
        assert repo.count() == 2

        # Cutoff intermedio
        cutoff = datetime(2024, 6, 1, tzinfo=UTC)
        deleted = repo.delete_older_than(cutoff)
        assert deleted == 1
        assert repo.count() == 1

    def test_delete_no_op_when_no_matches(
        self, repo: StressScenariosRepository
    ) -> None:
        repo.write(build_historical_scenarios()[0])
        # Cutoff in passato remoto: nessun match
        cutoff = datetime(2000, 1, 1, tzinfo=UTC)
        deleted = repo.delete_older_than(cutoff)
        assert deleted == 0
