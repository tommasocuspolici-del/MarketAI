# Observability & Health

Inspired by SRE practices: every component declares health, every error
is bounded, every action is measured.

## Health Status (Rule 30)

`SystemHealth` aggregates `ComponentHealth` from 4 probes:

| Component | Probe | Failure mode |
|-----------|-------|--------------|
| `duckdb` | `SELECT 1` | DOWN if connection fails |
| `sqlite` | `SELECT 1` | DOWN if path missing |
| `cache` | write+read sentinel | DEGRADED on mismatch |
| `scheduler` | APScheduler is-running | DEGRADED if not running |

States propagated to UI:

- 🟢 **OPERATIONAL** — all probes healthy
- 🟡 **DEGRADED** — partial data, critical analysis still works
- 🔴 **DOWN** — system cannot operate

## Error Budget

`shared/error_budget.py` tracks rolling 5-min error rate. If rate > 10%,
the scheduler auto-suspends and emits a critical alert. Configurable in
`config/default.yaml`.

## Metrics

`shared/metrics.py` keeps in-memory counters/timers:

- `fetch_latency_ms{source, ticker}`
- `fetch_errors_total{source}`
- `pipeline_duration_ms{stage}`
- `data_quality_score{series_id}`
- `cache_hits_total` / `cache_misses_total`

## Logging

Always `structlog` (Rule 6). Never `print()`. Logs are JSON-structured for
log-aggregation pipelines. Sensitive data NEVER logged (Rule 15).
