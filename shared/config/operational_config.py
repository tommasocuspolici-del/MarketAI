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

__version__ = "2.0.0"
__all__ = ["OP_CONFIG", "OperationalConfig", "_build_config_from_raw", "_build_stress_test"]


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
class _LabourMarketDefaults:
    weight_jolts: float
    weight_claims: float
    weight_payroll: float
    tight_score_min: float
    deteriorating_score_max: float
    balanced_min: float
    balanced_max: float


@dataclass(frozen=True, slots=True)
class _SentimentDefaults:
    pc_bullish_thresh: float
    pc_bearish_thresh: float
    cot_oi_spread: float
    short_int_neutral: float
    short_int_spread: float


@dataclass(frozen=True, slots=True)
class _StressScenarioParams:
    drift_adj: float
    vol_mult: float
    spike_days: int
    spike_mult: float


@dataclass(frozen=True, slots=True)
class _StressTestDefaults:
    seed: int
    recession: _StressScenarioParams
    inflation_shock: _StressScenarioParams
    credit_crisis: _StressScenarioParams
    goldilocks: _StressScenarioParams
    base: _StressScenarioParams


@dataclass(frozen=True, slots=True)
class OperationalConfig:
    """Configurazione operativa completa. Immutabile a runtime."""

    fx_fallbacks: _FxFallbacks
    http: _HttpDefaults
    cache: _CacheDefaults
    alerts: _AlertDefaults
    analytics: _AnalyticsDefaults
    etoro: _EtoroDefaults
    labour_market: _LabourMarketDefaults
    sentiment: _SentimentDefaults
    stress_test: _StressTestDefaults


# Valori di default — identici a config/operational_defaults.yaml.
# Usati quando il YAML non esiste (CI/tests senza config/).
# ⚠️ Questo è L'UNICO file .py autorizzato ad avere questi numeri.
_DEFAULTS: dict[str, Any] = {
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
    "labour_market": {
        "weight_jolts": 0.45,
        "weight_claims": 0.40,
        "weight_payroll": 0.15,
        "tight_score_min": 0.35,
        "deteriorating_score_max": -0.25,
        "balanced_min": -0.25,
        "balanced_max": 0.35,
    },
    "sentiment": {
        "pc_bullish_thresh": 0.70,
        "pc_bearish_thresh": 1.25,
        "cot_oi_spread": 0.25,
        "short_int_neutral": 0.01,
        "short_int_spread": 0.03,
    },
    "stress_test": {
        "seed": 42,
        "recession":       {"drift_adj": -0.0020, "vol_mult": 1.60, "spike_days": 0,  "spike_mult": 1.0},
        "inflation_shock": {"drift_adj": -0.0008, "vol_mult": 1.40, "spike_days": 5,  "spike_mult": 2.0},
        "credit_crisis":   {"drift_adj": -0.0030, "vol_mult": 1.80, "spike_days": 10, "spike_mult": 3.0},
        "goldilocks":      {"drift_adj":  0.0012, "vol_mult": 0.80, "spike_days": 0,  "spike_mult": 1.0},
        "base":            {"drift_adj":  0.0,    "vol_mult": 1.00, "spike_days": 0,  "spike_mult": 1.0},
    },
}


def _build_stress_test(raw_section: dict[str, Any]) -> _StressTestDefaults:
    """Costruisce _StressTestDefaults con merge per scenario."""
    defaults_st = _DEFAULTS["stress_test"]

    def _scenario(name: str) -> _StressScenarioParams:
        d = defaults_st[name]
        r = raw_section.get(name, {})
        p = {**d, **r}
        return _StressScenarioParams(**p)

    return _StressTestDefaults(
        seed=int(raw_section.get("seed", defaults_st["seed"])),
        recession=_scenario("recession"),
        inflation_shock=_scenario("inflation_shock"),
        credit_crisis=_scenario("credit_crisis"),
        goldilocks=_scenario("goldilocks"),
        base=_scenario("base"),
    )


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
        labour_market=_LabourMarketDefaults(**_m("labour_market")),
        sentiment=_SentimentDefaults(**_m("sentiment")),
        stress_test=_build_stress_test(raw.get("stress_test", {})),
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
