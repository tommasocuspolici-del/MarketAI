# 32 Invariable Conventions

These conventions are non-negotiable and apply across the entire codebase.
Each PR is rejected if any convention is violated.

## Architecture (1–10)

| # | Rule | Enforcement |
|---|------|-------------|
| 1 | LINGUA — code English, comments Italian, docstrings English | code review |
| 2 | SRP — single responsibility, ≤400 lines/file | code review |
| 3 | TIPI — type hints everywhere | `mypy --strict` |
| 4 | IMPORT — absolute, no circular, `__all__` in `__init__.py` | `ruff` |
| 5 | ERRORI — no generic except, custom exceptions | `ruff B902` |
| 6 | LOGGING — `structlog` only, no `print()` | code review |
| 7 | COSTANTI — `shared/constants.py` or YAML, zero magic numbers | code review |
| 8 | MATEMATICA — `numpy`/`scipy`, no native float for finance | code review |
| 9 | DATI — explicit Pandera schema, no "object" dtype | runtime validation |
| 10 | TEST — public function ⇒ unit test, coverage ≥ 80% | `pytest --cov` |

## Data & Persistence (11–17)

| # | Rule | Enforcement |
|---|------|-------------|
| 11 | ASYNC — always async/await for network | code review |
| 12 | DATA_PIPELINE — fetch→clean→validate→duckdb→cache→return | `BaseFetcher` ABC |
| 13 | DUCKDB — bulk historical = DuckDB, transactional = SQLite | code review |
| 14 | CLEAN_FIRST — `DataCleaner` BEFORE Pandera | `BaseFetcher` |
| 15 | SICUREZZA — no API keys in code, `.env` only | `bandit` + grep |
| 16 | VERSIONE — `__version__ = "X.Y.Z"` per module | grep |
| 17 | COMMIT — Conventional Commits | `commitlint` |

## Layer & Communication (18–22)

| # | Rule | Enforcement |
|---|------|-------------|
| 18 | VALUTE — explicit `Currency` enum + `fx_service.py` | `mypy` |
| 19 | DATE — UTC internally, no naive datetimes | `mypy` |
| 20 | UI — zero hardcoded values, `DESIGN_TOKENS` always | code review |
| 21 | LAYER — `engine/`↔`personal/` ONLY via `bridge/` | code review + grep |
| 22 | PROFILO — every suggestion via `InvestorProfile` | `SuitabilityChecker` |

## Analytical Quality (23–26)

| # | Rule | Enforcement |
|---|------|-------------|
| 23 | BACKTEST — VectorBT, no Python loops, fees+slippage+shift(1) | code review |
| 24 | STRESS_TEST — historical + forward-looking synthetic | code review |
| 25 | LATENCY — real-time data ≤ 60s | health check |
| 26 | DATA_QUALITY — `DataQualityReport` per series, score ≥ 0.7 critical | runtime |

## Operational (v6 — 27–32)

| # | Rule | Enforcement |
|---|------|-------------|
| 27 | DUCKDB_MIGRATIONS — versioned SQL files, auto-applied | `DuckDBMigrator` |
| 28 | RATE_BUDGET — every fetcher in `rate_limits.yaml` | `RateLimitManager` |
| 29 | FEATURE_FLAGS — expensive features YAML-gated | `feature_flags.py` |
| 30 | ERROR_BUDGET — error_rate>10%/5min ⇒ scheduler suspend | `error_budget.py` |
| 31 | DATA_RETENTION — monthly retention scripts | `duckdb_retention.py` |
| 32 | AUTH_UI — Streamlit auth required in production | `require_auth()` |

## Verification

Each rule has automated enforcement where possible. The pre-commit hooks
run `ruff` + `mypy` + a fast subset of `pytest` on every commit.
