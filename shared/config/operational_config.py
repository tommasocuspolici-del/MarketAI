"""Carica config/operational_defaults.yaml ed espone i valori come dataclass frozen.

Unico punto di accesso alle costanti operative. Elimina magic numbers (P4).

Uso::

    from shared.config.operational_config import OP_CONFIG
    timeout = OP_CONFIG.http.default_timeout_s
    ttl     = OP_CONFIG.cache.live_market_ttl_s
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import yaml

__version__ = "1.0.0"
__all__ = ["OP_CONFIG", "OperationalConfig", "_build_config_from_raw"]


@dataclass(frozen=True, slots=True)
class _FxFallbacks:
    gbp_usd: float
    eur_usd: float
    chf_usd: float


@dataclass(frozen=True, slots=True)
class _HttpDefaults:
    default_timeout_s: float
    max_retries: int
    retry_base_delay_s: float
    error_body_preview_bytes: int


@dataclass(frozen=True, slots=True)
class _CacheDefaults:
    live_market_ttl_s: int
    macro_conviction_ttl_s: int
    instrument_lookup_ttl_s: int
    scheduler_job_ttl_s: int
    equities_ohlcv_ttl_s: int
    disk_snapshot_max_age_s: int
    signals_disk_ttl_s: int


@dataclass(frozen=True, slots=True)
class _AlertDefaults:
    dedup_window_minutes: int


@dataclass(frozen=True, slots=True)
class _AnalyticsDefaults:
    extreme_greed_threshold: float
    vix_strategy_weight: float
    var_alpha: float
    backtesting_train_pct: float


@dataclass(frozen=True, slots=True)
class _EtoroDefaults:
    instrument_cache_max_age_days: int


@dataclass(frozen=True, slots=True)
class OperationalConfig:
    """Configurazione operativa completa. Immutabile a runtime."""

    fx_fallbacks: _FxFallbacks
    http: _HttpDefaults
    cache: _CacheDefaults
    alerts: _AlertDefaults
    analytics: _AnalyticsDefaults
    etoro: _EtoroDefaults


# Valori di default — identici a config/operational_defaults.yaml.
# Usati quando il YAML non esiste (CI/tests senza config/).
# ⚠️ Questo è L'UNICO file .py autorizzato ad avere questi numeri.
_DEFAULTS: dict[str, dict[str, Any]] = {
    "fx_fallbacks": {"gbp_usd": 1.27, "eur_usd": 1.08, "chf_usd": 1.12},
    "http": {
        "default_timeout_s": 15.0,
        "max_retries": 3,
        "retry_base_delay_s": 1.0,
        "error_body_preview_bytes": 2048,
    },
    "cache": {
        # 900s = 15 min (v9.0 rate-limit fix — deliberato)
        "live_market_ttl_s": 900,
        "macro_conviction_ttl_s": 3600,
        "instrument_lookup_ttl_s": 86400,
        "scheduler_job_ttl_s": 300,
        "equities_ohlcv_ttl_s": 300,
        "disk_snapshot_max_age_s": 86400,
        "signals_disk_ttl_s": 3600,
    },
    "alerts": {"dedup_window_minutes": 60},
    "analytics": {
        "extreme_greed_threshold": 0.60,
        "vix_strategy_weight": 0.60,
        "var_alpha": 0.05,
        "backtesting_train_pct": 0.60,
    },
    "etoro": {"instrument_cache_max_age_days": 7},
}


def _build_config_from_raw(raw: dict[str, Any]) -> OperationalConfig:
    """Costruisce OperationalConfig da dict (YAML o test). Testabile senza I/O."""
    def _m(section: str) -> dict[str, Any]:
        return {**_DEFAULTS.get(section, {}), **raw.get(section, {})}

    return OperationalConfig(
        fx_fallbacks=_FxFallbacks(**_m("fx_fallbacks")),
        http=_HttpDefaults(**_m("http")),
        cache=_CacheDefaults(**_m("cache")),
        alerts=_AlertDefaults(**_m("alerts")),
        analytics=_AnalyticsDefaults(**_m("analytics")),
        etoro=_EtoroDefaults(**_m("etoro")),
    )


@lru_cache(maxsize=1)
def _load() -> OperationalConfig:
    """Carica YAML e memorizza in cache (singleton). Fallback ai default se assente."""
    config_path = (
        pathlib.Path(__file__).parent.parent.parent / "config" / "operational_defaults.yaml"
    )
    if not config_path.exists():
        return _build_config_from_raw({})
    raw: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return _build_config_from_raw(raw)


#: Singleton globale.
OP_CONFIG: OperationalConfig = _load()
