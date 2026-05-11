"""Centralized constants — single source of truth.

Rule 7: No magic numbers in code. All constants either here or in YAML.
Rule 15: No secrets here — those belong in .env.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

__version__ = "6.0.0"

__all__ = [
    "BACKUP_DIR",
    "CONFIG_DIR",
    "DATA_DIR",
    "DATA_RETENTION_PATH",
    "DB_DIR",
    "DEFAULT_CONFIG",
    "DUCKDB_PATH",
    "FEATURE_FLAGS_PATH",
    "LOGS_DIR",
    "MIGRATIONS_DUCKDB_DIR",
    "PROJECT_ROOT",
    "RATE_LIMITS_PATH",
    "SQLITE_PATH",
    "load_yaml_config",
]


# ═══════════════════════════════════════════════════════════════════════════
# Filesystem paths
# ═══════════════════════════════════════════════════════════════════════════
# Risoluzione: parent(shared/) → project root. Robusto rispetto alla cwd.
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
CONFIG_DIR: Path = PROJECT_ROOT / "config"
DB_DIR: Path = PROJECT_ROOT / "db"
DATA_DIR: Path = PROJECT_ROOT / "data"
LOGS_DIR: Path = PROJECT_ROOT / "logs"

# Override via env variable se impostato
BACKUP_DIR: Path = Path(os.getenv("BACKUP_DIR", str(DATA_DIR / "backups")))

DUCKDB_PATH: Path = Path(os.getenv("DUCKDB_PATH", str(DB_DIR / "market_data.duckdb")))
SQLITE_PATH: Path = Path(os.getenv("SQLITE_PATH", str(DB_DIR / "personal.sqlite")))

# ═══════════════════════════════════════════════════════════════════════════
# Migrations
# ═══════════════════════════════════════════════════════════════════════════
MIGRATIONS_DUCKDB_DIR: Path = PROJECT_ROOT / "shared" / "db" / "migrations" / "duckdb"

# ═══════════════════════════════════════════════════════════════════════════
# Config files
# ═══════════════════════════════════════════════════════════════════════════
DEFAULT_CONFIG_PATH: Path = CONFIG_DIR / "default.yaml"
FEATURE_FLAGS_PATH: Path = CONFIG_DIR / "feature_flags.yaml"
RATE_LIMITS_PATH: Path = CONFIG_DIR / "rate_limits.yaml"
DATA_RETENTION_PATH: Path = CONFIG_DIR / "data_retention.yaml"


# ═══════════════════════════════════════════════════════════════════════════
# YAML loader (cached)
# ═══════════════════════════════════════════════════════════════════════════
@lru_cache(maxsize=32)
def load_yaml_config(path: Path) -> dict[str, Any]:
    """Load a YAML config file with caching.

    Args:
        path: Path to YAML file.

    Returns:
        Parsed YAML as dict. Empty dict if file missing.
    """
    if not path.exists():
        return {}
    content = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content) or {}
    if not isinstance(parsed, dict):
        raise TypeError(f"Expected dict at top level of {path}, got {type(parsed).__name__}")
    return parsed


# Caricamento eager: il default config serve fin dall'import
DEFAULT_CONFIG: dict[str, Any] = load_yaml_config(DEFAULT_CONFIG_PATH)


# ═══════════════════════════════════════════════════════════════════════════
# Numeric constants (Rule 7: zero magic numbers)
# ═══════════════════════════════════════════════════════════════════════════
# Calendari finanziari
TRADING_DAYS_PER_YEAR: int = 252
TRADING_DAYS_PER_MONTH: int = 21
MONTHS_PER_YEAR: int = 12
WEEKS_PER_YEAR: int = 52

# Default backtesting (Regola 23)
MIN_BACKTEST_FEES_BPS: float = 0.001  # 10 bps
MIN_BACKTEST_SLIPPAGE_BPS: float = 0.001  # 10 bps

# Data quality (Regola 26)
MIN_QUALITY_SCORE_CRITICAL: float = 0.5
MIN_QUALITY_SCORE_BACKTEST: float = 0.7

# Error budget (Regola 30)
DEFAULT_ERROR_BUDGET_WINDOW_MINUTES: int = 5
DEFAULT_ERROR_BUDGET_THRESHOLD_PCT: float = 10.0

# Cache TTL defaults (secondi)
CACHE_TTL_PRICES: int = 60
CACHE_TTL_MACRO: int = 3600
CACHE_TTL_FUNDAMENTALS: int = 86400


def _ensure_directories() -> None:
    """Create all required runtime directories if missing."""
    # Eseguito lazy al primo import ma in modo idempotente
    for directory in (DB_DIR, DATA_DIR, LOGS_DIR, BACKUP_DIR):
        directory.mkdir(parents=True, exist_ok=True)


_ensure_directories()
