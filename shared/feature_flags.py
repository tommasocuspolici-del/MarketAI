"""Feature flag loader (Rule 29).

Experimental or expensive features are gated by boolean flags read from
``config/feature_flags.yaml``. Default = False for safety.

Usage:
    from shared.feature_flags import is_enabled, require_enabled

    if is_enabled("realtime_websocket"):
        start_ws_feed()

    require_enabled("pytorch_forecasting")  # raises FeatureDisabledError if off
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path  # noqa: TC003 — Path is used at runtime in type annotations
from typing import Any

import yaml

from shared.constants import FEATURE_FLAGS_PATH
from shared.exceptions import ConfigurationError, FeatureDisabledError
from shared.logger import get_logger

__version__ = "6.0.0"

__all__ = ["FEATURE_FLAGS_PATH", "all_flags", "is_enabled", "reload_flags", "require_enabled"]

log = get_logger(__name__)


@lru_cache(maxsize=1)
def _load_flags() -> dict[str, bool]:
    """Load feature flags from YAML. Validates types (all values must be bool).

    Reads ``shared.feature_flags.FEATURE_FLAGS_PATH`` lazily so tests can
    monkeypatch it at runtime.
    """
    # Import locale: leggi il path dal namespace del modulo (post-monkeypatch)
    import shared.feature_flags as _module

    path: Path = _module.FEATURE_FLAGS_PATH
    if not path.exists():
        log.warning("feature_flags.missing", path=str(path))
        return {}

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigurationError(
            f"Feature flags file {path} must be a mapping, got {type(raw).__name__}"
        )

    # Validazione: ogni valore deve essere un bool nativo
    validated: dict[str, bool] = {}
    for key, value in raw.items():
        if not isinstance(value, bool):
            log.warning(
                "feature_flags.invalid_type",
                flag=key,
                value_type=type(value).__name__,
            )
            continue
        validated[str(key)] = value

    log.info("feature_flags.loaded", count=len(validated))
    return validated


def is_enabled(flag: str) -> bool:
    """Check whether a feature flag is enabled.

    Returns False for unknown flags (safe default, Rule 29).
    """
    flags = _load_flags()
    return flags.get(flag, False)


def require_enabled(flag: str) -> None:
    """Raise FeatureDisabledError if the flag is not enabled.

    Use as a guard at the top of expensive or experimental functions.
    """
    if not is_enabled(flag):
        raise FeatureDisabledError(
            f"Feature '{flag}' is disabled. "
            f"Enable in config/feature_flags.yaml to proceed."
        )


def all_flags() -> dict[str, bool]:
    """Return a copy of all currently loaded flags."""
    # Copia difensiva: il chiamante non deve poter mutare la cache
    return dict(_load_flags())


def reload_flags() -> None:
    """Clear the cache and force reload from disk.

    Useful in tests or after manual edits to feature_flags.yaml.
    """
    _load_flags.cache_clear()


# ═══════════════════════════════════════════════════════════════════════════
# Type guard helper
# ═══════════════════════════════════════════════════════════════════════════
def if_enabled(flag: str) -> bool:
    """Alias for is_enabled with a more 'natural' read: `if if_enabled("x"):`.

    (Kept for readability. Equivalent to is_enabled.)
    """
    return is_enabled(flag)


# Silenzia warning mypy: export interno per test
_internal_loader: Any = _load_flags
