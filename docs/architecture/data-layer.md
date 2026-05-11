# Data Layer (DuckDB + SQLite)

Two databases, two purposes (Rule 13):

## DuckDB — OLAP

Use for: massive append-only time-series data with heavy analytical
queries.

| Table | Purpose | Retention |
|-------|---------|-----------|
| `prices_ohlcv` | Daily OHLCV | 20 years |
| `macro_series` | FRED macro indicators | 30 years |
| `fundamentals_quarterly` | SEC EDGAR fundamentals | 20 years |
| `sentiment_signals` | Per-source sentiment readings | 3 years |
| `correlations` | DCC-GARCH-lite snapshots | 5 years |
| `data_quality_reports` | Per-series quality reports | 1 year |
| `backtest_results` | Strategy backtest outputs | 2 years |
| `stress_scenarios` | Historical + synthetic scenarios | Permanent |

## SQLite — OLTP

Use for: transactional/mutable data with frequent reads/writes.

| Table | Purpose | Retention |
|-------|---------|-----------|
| `investor_profiles` | Profile config | Permanent |
| `positions` | Imported positions | 10 years |
| `cash_flow_entries` | Income/expense | 10 years |
| `financial_goals` | SMART goals | Permanent |
| `wealth_snapshots` | Net worth snapshots | 10 years |
| `alert_history_personal` | Alert log | 1 year |

## Migrations

- **DuckDB**: custom `DuckDBMigrator` (Rule 27). SQL files versioned
  `YYYYMMDD_NNN_descrip.sql` in `shared/db/migrations/duckdb/`. Auto-applied
  on startup.
- **SQLite**: standard Alembic in `shared/db/migrations/sqlite/`.

## Backups

`BackupManager`: nightly via APScheduler, retains last 10 backups.
DuckDB exported as Parquet for portability + SQLite hot-copy.
