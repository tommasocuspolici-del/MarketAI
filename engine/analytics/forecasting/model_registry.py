"""Model Registry — Convenzione 33. Ogni modello ML registrato in DuckDB."""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

import pandas as pd

from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

log = get_logger(__name__)

TABLE_REGISTRY = "model_registry"
TABLE_WFO = "wfo_results"

# DDL per le tabelle (eseguite se non esistono)
_DDL_REGISTRY = f"""
CREATE TABLE IF NOT EXISTS {TABLE_REGISTRY} (
    model_id          VARCHAR PRIMARY KEY,
    model_type        VARCHAR NOT NULL,
    target_metric     VARCHAR NOT NULL,
    horizon_days      INTEGER NOT NULL,
    asset_class       VARCHAR,
    hyperparams       VARCHAR,        -- JSON serializzato
    dataset_hash      VARCHAR,
    train_start       DATE,
    train_end         DATE,
    val_start         DATE,
    val_end           DATE,
    mse_oos           DOUBLE,
    mae_oos           DOUBLE,
    mape_oos          DOUBLE,
    directional_acc   DOUBLE,
    sharpe_predictive DOUBLE,
    is_active         BOOLEAN DEFAULT TRUE,
    is_baseline_beaten BOOLEAN DEFAULT FALSE,
    notes             VARCHAR,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

_DDL_WFO = f"""
CREATE TABLE IF NOT EXISTS {TABLE_WFO} (
    id              VARCHAR PRIMARY KEY,
    model_id        VARCHAR NOT NULL,
    fold_n          INTEGER NOT NULL,
    train_start     DATE,
    train_end       DATE,
    test_start      DATE,
    test_end        DATE,
    mse             DOUBLE,
    mae             DOUBLE,
    directional_acc DOUBLE,
    sharpe_fold     DOUBLE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


@dataclass
class ModelEntry:
    model_id: str
    model_type: str           # arima|ridge|xgboost|lstm|var|prophet
    target_metric: str
    horizon_days: int
    asset_class: str | None
    hyperparams: dict[str, Any]
    dataset_hash: str
    train_start: date | None
    train_end: date | None
    val_start: date | None
    val_end: date | None
    mse_oos: float | None
    mae_oos: float | None
    mape_oos: float | None
    directional_acc: float | None
    sharpe_predictive: float | None
    is_active: bool
    is_baseline_beaten: bool
    notes: str | None


@dataclass
class WFOFoldResult:
    model_id: str
    fold_n: int
    train_start: date | None
    train_end: date | None
    test_start: date | None
    test_end: date | None
    mse: float
    mae: float
    directional_acc: float
    sharpe_fold: float


class ModelRegistry:
    """Persiste e recupera metadati e metriche di modelli ML in DuckDB."""

    def __init__(self, db: DuckDBClient) -> None:
        self._db = db
        self._ensure_tables()

    # ------------------------------------------------------------------ #
    # Schema management                                                    #
    # ------------------------------------------------------------------ #

    def _ensure_tables(self) -> None:
        try:
            self._db.execute(_DDL_REGISTRY)
            self._db.execute(_DDL_WFO)
            log.debug("model_registry.tables_ensured")
        except Exception as exc:
            log.error("model_registry.ddl_failed", error=str(exc))

    # ------------------------------------------------------------------ #
    # Registration                                                         #
    # ------------------------------------------------------------------ #

    def register(self, entry: ModelEntry) -> str:
        """Persiste un ModelEntry e restituisce model_id."""
        sql = f"""
        INSERT OR REPLACE INTO {TABLE_REGISTRY} (
            model_id, model_type, target_metric, horizon_days, asset_class,
            hyperparams, dataset_hash, train_start, train_end, val_start, val_end,
            mse_oos, mae_oos, mape_oos, directional_acc, sharpe_predictive,
            is_active, is_baseline_beaten, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            entry.model_id,
            entry.model_type,
            entry.target_metric,
            entry.horizon_days,
            entry.asset_class,
            json.dumps(entry.hyperparams),
            entry.dataset_hash,
            entry.train_start,
            entry.train_end,
            entry.val_start,
            entry.val_end,
            entry.mse_oos,
            entry.mae_oos,
            entry.mape_oos,
            entry.directional_acc,
            entry.sharpe_predictive,
            entry.is_active,
            entry.is_baseline_beaten,
            entry.notes,
        )
        self._db.execute(sql, list(params))
        log.info("model_registry.registered", model_id=entry.model_id, model_type=entry.model_type)
        return entry.model_id

    def register_new(
        self,
        model_type: str,
        target_metric: str,
        horizon_days: int,
        hyperparams: dict[str, Any],
        training_data: pd.DataFrame | None = None,
        **kwargs: Any,
    ) -> str:
        """Genera UUID, calcola dataset_hash e registra il modello."""
        model_id = str(uuid.uuid4())
        dataset_hash = (
            self.compute_dataset_hash(training_data)
            if training_data is not None
            else ""
        )
        entry = ModelEntry(
            model_id=model_id,
            model_type=model_type,
            target_metric=target_metric,
            horizon_days=horizon_days,
            asset_class=kwargs.get("asset_class"),
            hyperparams=hyperparams,
            dataset_hash=dataset_hash,
            train_start=kwargs.get("train_start"),
            train_end=kwargs.get("train_end"),
            val_start=kwargs.get("val_start"),
            val_end=kwargs.get("val_end"),
            mse_oos=kwargs.get("mse_oos"),
            mae_oos=kwargs.get("mae_oos"),
            mape_oos=kwargs.get("mape_oos"),
            directional_acc=kwargs.get("directional_acc"),
            sharpe_predictive=kwargs.get("sharpe_predictive"),
            is_active=kwargs.get("is_active", True),
            is_baseline_beaten=kwargs.get("is_baseline_beaten", False),
            notes=kwargs.get("notes"),
        )
        return self.register(entry)

    # ------------------------------------------------------------------ #
    # Updates                                                              #
    # ------------------------------------------------------------------ #

    def update_metrics(
        self,
        model_id: str,
        mse_oos: float,
        mae_oos: float,
        mape_oos: float,
        directional_acc: float,
        is_baseline_beaten: bool,
    ) -> None:
        sql = f"""
        UPDATE {TABLE_REGISTRY}
        SET mse_oos = ?, mae_oos = ?, mape_oos = ?, directional_acc = ?,
            is_baseline_beaten = ?
        WHERE model_id = ?
        """
        self._db.execute(sql, [mse_oos, mae_oos, mape_oos, directional_acc, is_baseline_beaten, model_id])
        log.info("model_registry.metrics_updated", model_id=model_id)

    def set_active(self, model_id: str, active: bool = True) -> None:
        sql = f"UPDATE {TABLE_REGISTRY} SET is_active = ? WHERE model_id = ?"
        self._db.execute(sql, [active, model_id])
        log.info("model_registry.active_set", model_id=model_id, active=active)

    # ------------------------------------------------------------------ #
    # Queries                                                              #
    # ------------------------------------------------------------------ #

    def get(self, model_id: str) -> ModelEntry | None:
        sql = f"SELECT * FROM {TABLE_REGISTRY} WHERE model_id = ?"
        try:
            rows = self._db.execute(sql, [model_id]).fetchdf()
        except Exception as exc:
            log.error("model_registry.get_failed", error=str(exc))
            return None
        if rows.empty:
            return None
        return self._row_to_entry(rows.iloc[0])

    def get_active(self, model_type: str | None = None) -> list[ModelEntry]:
        if model_type:
            sql = f"SELECT * FROM {TABLE_REGISTRY} WHERE is_active = TRUE AND model_type = ?"
            params: list[Any] = [model_type]
        else:
            sql = f"SELECT * FROM {TABLE_REGISTRY} WHERE is_active = TRUE"
            params = []
        try:
            rows = self._db.execute(sql, params).fetchdf() if params else self._db.execute(sql).fetchdf()
        except Exception as exc:
            log.error("model_registry.get_active_failed", error=str(exc))
            return []
        return [self._row_to_entry(row) for _, row in rows.iterrows()]

    def get_best(self, target_metric: str, horizon_days: int) -> ModelEntry | None:
        """Restituisce il modello con il minore mse_oos per metrica e orizzonte."""
        sql = f"""
        SELECT * FROM {TABLE_REGISTRY}
        WHERE target_metric = ? AND horizon_days = ? AND mse_oos IS NOT NULL
        ORDER BY mse_oos ASC
        LIMIT 1
        """
        try:
            rows = self._db.execute(sql, [target_metric, horizon_days]).fetchdf()
        except Exception as exc:
            log.error("model_registry.get_best_failed", error=str(exc))
            return None
        if rows.empty:
            return None
        return self._row_to_entry(rows.iloc[0])

    # ------------------------------------------------------------------ #
    # WFO persistence                                                      #
    # ------------------------------------------------------------------ #

    def save_wfo_fold(self, fold: WFOFoldResult) -> None:
        fold_id = str(uuid.uuid4())
        sql = f"""
        INSERT INTO {TABLE_WFO} (
            id, model_id, fold_n, train_start, train_end,
            test_start, test_end, mse, mae, directional_acc, sharpe_fold
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self._db.execute(sql, [
            fold_id, fold.model_id, fold.fold_n,
            fold.train_start, fold.train_end,
            fold.test_start, fold.test_end,
            fold.mse, fold.mae, fold.directional_acc, fold.sharpe_fold,
        ])
        log.debug("model_registry.wfo_fold_saved", model_id=fold.model_id, fold_n=fold.fold_n)

    def get_wfo_results(self, model_id: str) -> pd.DataFrame:
        sql = f"SELECT * FROM {TABLE_WFO} WHERE model_id = ? ORDER BY fold_n"
        try:
            return self._db.execute(sql, [model_id]).fetchdf()
        except Exception as exc:
            log.error("model_registry.get_wfo_failed", error=str(exc))
            return pd.DataFrame()

    # ------------------------------------------------------------------ #
    # Static helpers                                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_dataset_hash(data: pd.DataFrame) -> str:
        """SHA-256 delle caratteristiche strutturali del DataFrame.

        Include: shape, dtypes, prime 5 righe, ultime 5 righe.
        """
        parts: list[str] = [
            str(data.shape),
            str(data.dtypes.to_dict()),
            data.head(5).to_csv(index=False),
            data.tail(5).to_csv(index=False),
        ]
        raw = "|".join(parts).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _row_to_entry(row: Any) -> ModelEntry:
        hyperparams = row.get("hyperparams") or "{}"
        if isinstance(hyperparams, str):
            try:
                hyperparams = json.loads(hyperparams)
            except (json.JSONDecodeError, ValueError):
                hyperparams = {}

        def _to_date(val: Any) -> date | None:
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return None
            if isinstance(val, pd.Timestamp):
                return val.date()
            if isinstance(val, datetime):
                return val.date()
            if isinstance(val, date):
                return val
            try:
                return pd.Timestamp(val).date()
            except Exception:
                return None

        def _to_float(val: Any) -> float | None:
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return None
            return float(val)

        return ModelEntry(
            model_id=str(row["model_id"]),
            model_type=str(row["model_type"]),
            target_metric=str(row["target_metric"]),
            horizon_days=int(row["horizon_days"]),
            asset_class=row.get("asset_class") or None,
            hyperparams=hyperparams,
            dataset_hash=str(row.get("dataset_hash") or ""),
            train_start=_to_date(row.get("train_start")),
            train_end=_to_date(row.get("train_end")),
            val_start=_to_date(row.get("val_start")),
            val_end=_to_date(row.get("val_end")),
            mse_oos=_to_float(row.get("mse_oos")),
            mae_oos=_to_float(row.get("mae_oos")),
            mape_oos=_to_float(row.get("mape_oos")),
            directional_acc=_to_float(row.get("directional_acc")),
            sharpe_predictive=_to_float(row.get("sharpe_predictive")),
            is_active=bool(row.get("is_active", True)),
            is_baseline_beaten=bool(row.get("is_baseline_beaten", False)),
            notes=row.get("notes") or None,
        )
