"""Tests for ModelRegistry."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch
import uuid

import duckdb
import pandas as pd
import pytest

from engine.analytics.forecasting.model_registry import (
    ModelEntry,
    ModelRegistry,
    WFOFoldResult,
)


# ─── Fixtures ────────────────────────────────────────────────────────────── #

@pytest.fixture
def in_memory_db():
    """DuckDBClient backed by an in-memory DuckDB connection."""
    conn = duckdb.connect(":memory:")

    class FakeClient:
        def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
            self._conn = connection

        def execute(self, sql: str, params=None):
            if params is not None:
                return self._conn.execute(sql, params)
            return self._conn.execute(sql)

    return FakeClient(conn)


@pytest.fixture
def registry(in_memory_db) -> ModelRegistry:
    return ModelRegistry(in_memory_db)


def _make_entry(model_id: str | None = None) -> ModelEntry:
    return ModelEntry(
        model_id=model_id or str(uuid.uuid4()),
        model_type="ridge",
        target_metric="UNRATE",
        horizon_days=30,
        asset_class="macro",
        hyperparams={"alpha": 1.0, "fit_intercept": True},
        dataset_hash="abc123",
        train_start=date(2020, 1, 1),
        train_end=date(2022, 12, 31),
        val_start=date(2023, 1, 1),
        val_end=date(2023, 12, 31),
        mse_oos=0.05,
        mae_oos=0.18,
        mape_oos=2.5,
        directional_acc=0.62,
        sharpe_predictive=0.85,
        is_active=True,
        is_baseline_beaten=True,
        notes="Test entry",
    )


# ─── Tests: register ─────────────────────────────────────────────────────── #

class TestRegister:
    def test_register_returns_model_id(self, registry: ModelRegistry) -> None:
        entry = _make_entry()
        result = registry.register(entry)
        assert result == entry.model_id

    def test_register_new_returns_uuid(self, registry: ModelRegistry) -> None:
        model_id = registry.register_new(
            model_type="arima",
            target_metric="CPIAUCSL",
            horizon_days=90,
            hyperparams={"order": (1, 1, 1)},
        )
        # Verifica che sia un UUID valido
        uuid.UUID(model_id)  # raises ValueError se non valido

    def test_register_new_with_training_data(self, registry: ModelRegistry) -> None:
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        model_id = registry.register_new(
            model_type="ridge",
            target_metric="GDPC1",
            horizon_days=60,
            hyperparams={"alpha": 0.5},
            training_data=df,
        )
        entry = registry.get(model_id)
        assert entry is not None
        assert entry.dataset_hash != ""


# ─── Tests: get ──────────────────────────────────────────────────────────── #

class TestGet:
    def test_get_retrieves_registered_entry(self, registry: ModelRegistry) -> None:
        entry = _make_entry()
        registry.register(entry)

        retrieved = registry.get(entry.model_id)

        assert retrieved is not None
        assert retrieved.model_id == entry.model_id
        assert retrieved.model_type == "ridge"
        assert retrieved.target_metric == "UNRATE"
        assert retrieved.horizon_days == 30

    def test_get_nonexistent_returns_none(self, registry: ModelRegistry) -> None:
        result = registry.get("nonexistent-id")
        assert result is None

    def test_get_restores_hyperparams(self, registry: ModelRegistry) -> None:
        entry = _make_entry()
        registry.register(entry)
        retrieved = registry.get(entry.model_id)
        assert retrieved is not None
        assert retrieved.hyperparams == {"alpha": 1.0, "fit_intercept": True}

    def test_get_restores_dates(self, registry: ModelRegistry) -> None:
        entry = _make_entry()
        registry.register(entry)
        retrieved = registry.get(entry.model_id)
        assert retrieved is not None
        assert retrieved.train_start == date(2020, 1, 1)
        assert retrieved.train_end == date(2022, 12, 31)


# ─── Tests: compute_dataset_hash ─────────────────────────────────────────── #

class TestComputeDatasetHash:
    def test_returns_consistent_sha256(self) -> None:
        df = pd.DataFrame({"x": [1, 2, 3], "y": [4.0, 5.0, 6.0]})
        h1 = ModelRegistry.compute_dataset_hash(df)
        h2 = ModelRegistry.compute_dataset_hash(df)
        assert h1 == h2

    def test_different_data_different_hash(self) -> None:
        df1 = pd.DataFrame({"x": [1, 2, 3]})
        df2 = pd.DataFrame({"x": [4, 5, 6]})
        assert ModelRegistry.compute_dataset_hash(df1) != ModelRegistry.compute_dataset_hash(df2)

    def test_hash_is_64_chars(self) -> None:
        df = pd.DataFrame({"a": [1]})
        h = ModelRegistry.compute_dataset_hash(df)
        assert len(h) == 64  # SHA-256 hex = 64 chars


# ─── Tests: update_metrics ───────────────────────────────────────────────── #

class TestUpdateMetrics:
    def test_update_metrics_updates_entry(self, registry: ModelRegistry) -> None:
        entry = _make_entry()
        registry.register(entry)

        registry.update_metrics(
            model_id=entry.model_id,
            mse_oos=0.01,
            mae_oos=0.08,
            mape_oos=1.2,
            directional_acc=0.75,
            is_baseline_beaten=True,
        )

        updated = registry.get(entry.model_id)
        assert updated is not None
        assert abs(updated.mse_oos - 0.01) < 1e-9
        assert abs(updated.mae_oos - 0.08) < 1e-9
        assert abs(updated.directional_acc - 0.75) < 1e-9
        assert updated.is_baseline_beaten is True


# ─── Tests: get_active & get_best ────────────────────────────────────────── #

class TestGetActiveAndBest:
    def test_get_active_returns_active_entries(self, registry: ModelRegistry) -> None:
        e1 = _make_entry()
        e2 = _make_entry()
        e2.is_active = False

        registry.register(e1)
        registry.register(e2)

        active = registry.get_active()
        ids = [e.model_id for e in active]
        assert e1.model_id in ids
        assert e2.model_id not in ids

    def test_get_active_filtered_by_type(self, registry: ModelRegistry) -> None:
        e_ridge = _make_entry()
        e_ridge.model_type = "ridge"

        e_arima = _make_entry()
        e_arima.model_type = "arima"

        registry.register(e_ridge)
        registry.register(e_arima)

        ridge_active = registry.get_active(model_type="ridge")
        assert all(e.model_type == "ridge" for e in ridge_active)

    def test_get_best_returns_lowest_mse(self, registry: ModelRegistry) -> None:
        e1 = _make_entry()
        e1.mse_oos = 0.10
        e1.target_metric = "UNRATE"
        e1.horizon_days = 30

        e2 = _make_entry()
        e2.mse_oos = 0.02
        e2.target_metric = "UNRATE"
        e2.horizon_days = 30

        registry.register(e1)
        registry.register(e2)

        best = registry.get_best("UNRATE", 30)
        assert best is not None
        assert best.model_id == e2.model_id


# ─── Tests: WFO fold persistence ─────────────────────────────────────────── #

class TestWFOFoldPersistence:
    def test_save_and_retrieve_wfo_fold(self, registry: ModelRegistry) -> None:
        entry = _make_entry()
        registry.register(entry)

        fold = WFOFoldResult(
            model_id=entry.model_id,
            fold_n=0,
            train_start=date(2020, 1, 1),
            train_end=date(2022, 12, 31),
            test_start=date(2023, 1, 1),
            test_end=date(2023, 12, 31),
            mse=0.05,
            mae=0.18,
            directional_acc=0.62,
            sharpe_fold=0.85,
        )
        registry.save_wfo_fold(fold)

        df = registry.get_wfo_results(entry.model_id)
        assert not df.empty
        assert df.iloc[0]["fold_n"] == 0
