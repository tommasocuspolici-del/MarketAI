"""cache_ttl_config — loader per config/cache_ttl.yaml (Regola 34).

Uso::

    from shared.config.cache_ttl_config import CACHE_TTL

    ttl = CACHE_TTL.get("prezzi_realtime")   # → 60
    ttl = CACHE_TTL.get("macro_fred")        # → 86400
    ttl = CACHE_TTL.get("unknown", 3600)     # → 3600 (default)
"""
from __future__ import annotations

import pathlib
from functools import lru_cache

import yaml

__version__ = "1.0.0"
__all__ = ["CACHE_TTL", "CacheTTLConfig"]

_CONFIG_PATH = pathlib.Path(__file__).parent.parent.parent / "config" / "cache_ttl.yaml"


class CacheTTLConfig:
    """Accesso type-safe ai TTL da cache_ttl.yaml."""

    def __init__(self, data: dict[str, int]) -> None:
        self._data = data

    def get(self, key: str, default: int = 3600) -> int:
        """Restituisce il TTL in secondi per la categoria data."""
        return int(self._data.get(key, default))

    def __getitem__(self, key: str) -> int:
        return int(self._data[key])

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def all(self) -> dict[str, int]:
        return dict(self._data)


@lru_cache(maxsize=1)
def _load() -> CacheTTLConfig:
    with _CONFIG_PATH.open(encoding="utf-8") as f:
        raw: dict = yaml.safe_load(f) or {}
    data = {k: int(v) for k, v in raw.items() if isinstance(v, (int, float))}
    return CacheTTLConfig(data)


CACHE_TTL: CacheTTLConfig = _load()
