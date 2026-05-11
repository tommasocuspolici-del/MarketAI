"""Global pytest fixtures and configuration."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════════
# Logging setup for tests
# ═══════════════════════════════════════════════════════════════════════════
@pytest.fixture(autouse=True)
def _configure_test_logging() -> None:
    """Minimize log noise during tests."""
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    os.environ.setdefault("LOG_FORMAT", "console")


# ═══════════════════════════════════════════════════════════════════════════
# Temp DB paths (avoid polluting real db/ dir)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.fixture
def tmp_duckdb_path(tmp_path: Path) -> Path:
    """Ephemeral DuckDB file path for isolated tests."""
    return tmp_path / "test_market.duckdb"


@pytest.fixture
def tmp_sqlite_path(tmp_path: Path) -> Path:
    """Ephemeral SQLite file path for isolated tests."""
    return tmp_path / "test_personal.sqlite"


@pytest.fixture
def tmp_backup_dir(tmp_path: Path) -> Path:
    """Ephemeral backup directory."""
    d = tmp_path / "backups"
    d.mkdir()
    return d


# ═══════════════════════════════════════════════════════════════════════════
# Reset singletons between tests
# ═══════════════════════════════════════════════════════════════════════════
@pytest.fixture(autouse=True)
def _reset_singletons() -> Iterator[None]:
    """Reset module-level singletons that can leak between tests."""
    yield
    # Teardown: reset dopo ogni test per evitare cross-contaminazione
    try:
        from shared.db.duckdb_client import reset_duckdb_client

        reset_duckdb_client()
    except ImportError:
        pass
    try:
        from shared.db.sqlite_client import reset_sqlite_client

        reset_sqlite_client()
    except ImportError:
        pass
    try:
        from shared.metrics import metrics

        metrics.reset()
    except ImportError:
        pass
    try:
        from shared.error_budget import error_budget

        # Regola 30: error budget è un singleton process-wide; va resettato
        # tra test per evitare leak di eventi recordati in test precedenti
        error_budget.reset()
    except ImportError:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# Personal layer fixture — SQLite + Alembic migrations applied
# ═══════════════════════════════════════════════════════════════════════════
@pytest.fixture
def personal_sqlite_client(tmp_sqlite_path: Path):  # type: ignore[no-untyped-def]
    """Fresh SQLite client with all personal-layer tables created.

    Bypasses Alembic and creates schema directly via SQLAlchemy core
    (faster + no Alembic config required in tests).
    """
    from sqlalchemy import text

    from shared.db.sqlite_client import SQLiteClient

    client = SQLiteClient(path=tmp_sqlite_path)

    # Crea le tabelle del personal layer direttamente (bypass Alembic in test)
    schema_sql = [
        """CREATE TABLE IF NOT EXISTS investor_profiles (
            profile_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            risk_tolerance TEXT NOT NULL,
            max_drawdown_pct REAL NOT NULL,
            investment_horizon TEXT NOT NULL,
            horizon_years INTEGER NOT NULL,
            liquidity_reserve_months INTEGER NOT NULL,
            financial_knowledge INTEGER NOT NULL,
            allowed_asset_classes TEXT NOT NULL,
            excluded_sectors TEXT NOT NULL DEFAULT '[]',
            excluded_countries TEXT NOT NULL DEFAULT '[]',
            base_currency TEXT NOT NULL DEFAULT 'EUR',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS positions (
            position_id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL REFERENCES investor_profiles(profile_id),
            ticker TEXT NOT NULL,
            exchange TEXT,
            asset_class TEXT NOT NULL,
            quantity REAL NOT NULL,
            avg_cost REAL NOT NULL,
            currency TEXT NOT NULL,
            opened_at TIMESTAMP NOT NULL,
            closed_at TIMESTAMP,
            is_open BOOLEAN NOT NULL DEFAULT 1,
            source TEXT NOT NULL DEFAULT 'etoro',
            imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS cash_flow_entries (
            entry_id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL REFERENCES investor_profiles(profile_id),
            occurred_at DATE NOT NULL,
            direction TEXT NOT NULL,
            category TEXT NOT NULL,
            subcategory TEXT,
            amount REAL NOT NULL,
            currency TEXT NOT NULL,
            description TEXT,
            is_recurring BOOLEAN NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS financial_goals (
            goal_id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL REFERENCES investor_profiles(profile_id),
            name TEXT NOT NULL,
            description TEXT,
            target_amount REAL NOT NULL,
            currency TEXT NOT NULL,
            target_date DATE NOT NULL,
            current_amount REAL NOT NULL DEFAULT 0.0,
            priority INTEGER NOT NULL DEFAULT 3,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS wealth_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL REFERENCES investor_profiles(profile_id),
            captured_at TIMESTAMP NOT NULL,
            total_assets REAL NOT NULL,
            total_liabilities REAL NOT NULL,
            net_worth REAL NOT NULL,
            currency TEXT NOT NULL,
            breakdown_json TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS assets (
            asset_id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL REFERENCES investor_profiles(profile_id),
            asset_type TEXT NOT NULL,
            name TEXT NOT NULL,
            current_value REAL NOT NULL,
            currency TEXT NOT NULL,
            last_updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            metadata_json TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS liabilities (
            liability_id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL REFERENCES investor_profiles(profile_id),
            name TEXT NOT NULL,
            current_balance REAL NOT NULL,
            currency TEXT NOT NULL,
            last_updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
    ]
    with client.engine.begin() as conn:
        for ddl in schema_sql:
            conn.execute(text(ddl))

    yield client
    client.close()
