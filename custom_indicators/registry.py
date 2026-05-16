"""CustomIndicatorRegistry — CRUD for indicator definitions (YAML + runtime).

Loads indicator definitions from config/custom_indicators.yaml on first access.
Supports runtime registration of library-based and DSL-based indicators.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from shared.constants import CONFIG_DIR
from shared.logger import get_logger

__version__ = "10.0.0"

__all__ = [
    "IndicatorDefinition",
    "CustomIndicatorRegistry",
    "get_indicator_registry",
]

log = get_logger(__name__)

_CONFIG_PATH = CONFIG_DIR / "custom_indicators.yaml"


@dataclass
class IndicatorDefinition:
    id:            str
    name:          str
    active:        bool               = True
    output_type:   str                = "float"    # "float" | "boolean"
    library_class: str | None         = None       # Pre-built class name
    expression:    str | None         = None       # DSL expression
    params:        dict[str, Any]     = field(default_factory=dict)
    description:   str                = ""


class CustomIndicatorRegistry:
    """In-memory registry of custom indicator definitions.

    Loaded from config/custom_indicators.yaml at first access.
    Thread-safe via RLock.
    """

    def __init__(self) -> None:
        self._indicators: dict[str, IndicatorDefinition] = {}
        self._lock = threading.RLock()
        self._loaded = False

    # ── Loading ────────────────────────────────────────────────────────────

    def load_from_yaml(self, path: Path | None = None) -> int:
        """Load indicator definitions from YAML. Returns count loaded."""
        path = path or _CONFIG_PATH
        if not path.exists():
            log.warning("indicator_registry.yaml_not_found", path=str(path))
            return 0

        raw = yaml.safe_load(path.read_text())
        indicators = raw.get("indicators", [])

        with self._lock:
            for entry in indicators:
                defn = IndicatorDefinition(
                    id            = entry["id"],
                    name          = entry.get("name", entry["id"]),
                    active        = bool(entry.get("active", True)),
                    output_type   = entry.get("output_type", "float"),
                    library_class = entry.get("library_class"),
                    expression    = entry.get("expression"),
                    params        = entry.get("params", {}),
                    description   = entry.get("description", ""),
                )
                self._indicators[defn.id] = defn
            self._loaded = True

        log.info("indicator_registry.loaded", count=len(indicators))
        return len(indicators)

    def _ensure_loaded(self) -> None:
        with self._lock:
            if not self._loaded:
                self.load_from_yaml()

    # ── CRUD ───────────────────────────────────────────────────────────────

    def register(self, defn: IndicatorDefinition) -> None:
        with self._lock:
            self._indicators[defn.id] = defn
        log.info("indicator_registry.registered", id=defn.id)

    def get(self, indicator_id: str) -> IndicatorDefinition | None:
        self._ensure_loaded()
        with self._lock:
            return self._indicators.get(indicator_id)

    def list_all(self) -> list[IndicatorDefinition]:
        self._ensure_loaded()
        with self._lock:
            return list(self._indicators.values())

    def list_active(self) -> list[IndicatorDefinition]:
        return [d for d in self.list_all() if d.active]

    def deactivate(self, indicator_id: str) -> bool:
        with self._lock:
            defn = self._indicators.get(indicator_id)
            if defn is None:
                return False
            self._indicators[indicator_id] = IndicatorDefinition(
                **{**defn.__dict__, "active": False}
            )
        return True

    def remove(self, indicator_id: str) -> bool:
        with self._lock:
            return self._indicators.pop(indicator_id, None) is not None


# ── Singleton ──────────────────────────────────────────────────────────────

_registry: CustomIndicatorRegistry | None = None
_lock = threading.Lock()


def get_indicator_registry() -> CustomIndicatorRegistry:
    global _registry
    if _registry is None:
        with _lock:
            if _registry is None:
                _registry = CustomIndicatorRegistry()
    return _registry
