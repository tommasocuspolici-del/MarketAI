"""Thin shared wrapper around engine.analytics.forecasting.model_registry.

Espone ModelRegistryClient ai layer bridge/shared senza dipendenza diretta da engine.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient
    from engine.analytics.forecasting.model_registry import ModelEntry

log = get_logger(__name__)


class ModelRegistryClient:
    """Wrapper leggero per uso nei layer bridge/shared.

    Delega tutte le operazioni a engine.analytics.forecasting.model_registry.ModelRegistry
    usando un'importazione lazy per rispettare i boundary architetturali.
    """

    def __init__(self, db: DuckDBClient) -> None:
        self._db = db
        self._registry: Any | None = None

    def _get_registry(self) -> Any:
        """Importazione lazy per evitare dipendenza circolare a import time."""
        if self._registry is None:
            from engine.analytics.forecasting.model_registry import ModelRegistry
            self._registry = ModelRegistry(self._db)
        return self._registry

    def get_active_models(self, model_type: str | None = None) -> list[Any]:
        """Restituisce la lista dei modelli attivi, opzionalmente filtrata per tipo."""
        try:
            return self._get_registry().get_active(model_type=model_type)
        except Exception as exc:
            log.error("model_registry_client.get_active_failed", error=str(exc))
            return []

    def get_best_model(self, target_metric: str, horizon_days: int) -> Any | None:
        """Restituisce il modello con il minore mse_oos per metrica e orizzonte."""
        try:
            return self._get_registry().get_best(target_metric, horizon_days)
        except Exception as exc:
            log.error("model_registry_client.get_best_failed", error=str(exc))
            return None

    def is_baseline_beaten(self, model_id: str) -> bool:
        """Verifica se il modello ha battuto il baseline."""
        try:
            entry = self._get_registry().get(model_id)
            if entry is None:
                return False
            return bool(entry.is_baseline_beaten)
        except Exception as exc:
            log.error("model_registry_client.is_baseline_beaten_failed", error=str(exc))
            return False
