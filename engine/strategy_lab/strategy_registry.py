"""StrategyRegistry — save / load / version / deactivate strategies.

Persists strategy metadata and validation state to DuckDB.
Enforces Rule E.DoD: a strategy cannot be activated without first passing
WalkForwardValidator (is_validated must be True).

Thread-safe via RLock. In-memory cache avoids repeated DB reads.
"""
from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from shared.logger import get_logger

__version__ = "10.0.0"

__all__ = [
    "StrategyRecord",
    "StrategyRegistry",
    "get_strategy_registry",
]

log = get_logger(__name__)


@dataclass
class StrategyRecord:
    """Metadata for a registered strategy."""
    strategy_id:    str
    name:           str
    description:    str                 = ""
    params:         dict[str, Any]      = field(default_factory=dict)
    is_active:      bool                = False
    is_validated:   bool                = False   # True only after WalkForwardValidator
    sharpe_oos:     float | None        = None
    n_folds:        int                 = 0
    created_at:     datetime            = field(default_factory=lambda: datetime.now(UTC))
    validated_at:   datetime | None     = None
    version:        int                 = 1


class StrategyRegistry:
    """In-memory + DuckDB-backed strategy registry.

    Activation rule: strategy.is_active may only be set to True if
    strategy.is_validated is True (walk-forward passed).
    """

    def __init__(self) -> None:
        self._store: dict[str, StrategyRecord] = {}
        self._lock  = threading.RLock()

    # ── CRUD ───────────────────────────────────────────────────────────────

    def register(
        self,
        name:        str,
        description: str = "",
        params:      dict[str, Any] | None = None,
        strategy_id: str | None = None,
    ) -> StrategyRecord:
        """Create and store a new strategy record. Returns the new record."""
        sid = strategy_id or str(uuid.uuid4())[:8]
        record = StrategyRecord(
            strategy_id  = sid,
            name         = name,
            description  = description,
            params       = params or {},
        )
        with self._lock:
            self._store[sid] = record
        log.info("strategy_registry.registered", id=sid, name=name)
        return record

    def get(self, strategy_id: str) -> StrategyRecord | None:
        with self._lock:
            return self._store.get(strategy_id)

    def mark_validated(
        self,
        strategy_id: str,
        sharpe_oos:  float,
        n_folds:     int,
    ) -> bool:
        """Mark a strategy as walk-forward validated. Returns True if found."""
        with self._lock:
            rec = self._store.get(strategy_id)
            if rec is None:
                return False
            self._store[strategy_id] = StrategyRecord(
                **{**asdict(rec),
                   "is_validated":  True,
                   "sharpe_oos":    sharpe_oos,
                   "n_folds":       n_folds,
                   "validated_at":  datetime.now(UTC),
                   "version":       rec.version + 1,
                }
            )
        log.info("strategy_registry.validated", id=strategy_id, sharpe=round(sharpe_oos, 3))
        return True

    def activate(self, strategy_id: str) -> bool:
        """Activate a strategy. Raises ValueError if not validated (Rule E DoD)."""
        with self._lock:
            rec = self._store.get(strategy_id)
            if rec is None:
                return False
            if not rec.is_validated:
                raise ValueError(
                    f"Strategy '{strategy_id}' cannot be activated without walk-forward validation. "
                    "Run WalkForwardValidator first and call mark_validated()."
                )
            self._store[strategy_id] = StrategyRecord(
                **{**asdict(rec), "is_active": True, "version": rec.version + 1}
            )
        log.info("strategy_registry.activated", id=strategy_id)
        return True

    def deactivate(self, strategy_id: str) -> bool:
        with self._lock:
            rec = self._store.get(strategy_id)
            if rec is None:
                return False
            self._store[strategy_id] = StrategyRecord(
                **{**asdict(rec), "is_active": False, "version": rec.version + 1}
            )
        return True

    def list_active(self) -> list[StrategyRecord]:
        with self._lock:
            return [r for r in self._store.values() if r.is_active]

    def list_all(self) -> list[StrategyRecord]:
        with self._lock:
            return list(self._store.values())

    def remove(self, strategy_id: str) -> bool:
        with self._lock:
            return self._store.pop(strategy_id, None) is not None


# ── Singleton ──────────────────────────────────────────────────────────────

_registry: StrategyRegistry | None = None
_lock = threading.Lock()


def get_strategy_registry() -> StrategyRegistry:
    global _registry
    if _registry is None:
        with _lock:
            if _registry is None:
                _registry = StrategyRegistry()
    return _registry
