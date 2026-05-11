# Deployment Guide (Docker)

## Quick Deploy

```bash
# 1. Configure
cp .env.docker.example .env.docker
# Edit and fill in API keys + auth password hash

# 2. Build and start
docker-compose up -d --build

# 3. Verify
curl http://localhost:8501/_stcore/health
docker-compose logs -f
```

## Architecture

`docker-compose.yml` runs two containers:

- **market_ai_app** — Streamlit dashboard on port 8501
- **market_ai_scheduler** — APScheduler for retention + periodic fetches

Both share the same `/data` volume mounted from the host.

## Volumes

| Path (container) | Path (host) | Contents |
|------------------|-------------|----------|
| `/data` | `./data` | DuckDB, SQLite, cache, backups |
| `/app/config` | `./config` | YAML configs |
| `/app/logs` | `./logs` | Application logs |

## Healthchecks

```yaml
healthcheck:
  test: ["CMD", "wget", "--spider", "http://localhost:8501/_stcore/health"]
  interval: 30s
  timeout: 10s
  retries: 3
```

If error_rate > 10% for 5 min, the container's `error_budget` flag turns
the health response from 200 → 503, marking it unhealthy.

## Backup

```bash
# Manual backup
docker-compose exec market_ai_app python -m scripts.backup

# Backups are written to /data/backups inside the container,
# which maps to ./data/backups on the host.
```

## Restore

```bash
# 1. Stop services
docker-compose stop

# 2. Restore from a tar.gz backup
tar xzf data/backups/backup_YYYYMMDD_HHMMSS.tar.gz -C /tmp/restore
cp /tmp/restore/sqlite.db data/personal.sqlite
# DuckDB: re-import from Parquet
docker run --rm -v $(pwd)/data:/data duckdb/duckdb \
  duckdb /data/market_data.duckdb \
  "IMPORT DATABASE '/tmp/restore/duckdb';"

# 3. Restart
docker-compose start
```

## Production Checklist

- [ ] `STREAMLIT_AUTH_ENABLED=true` and password hash set (Rule 32)
- [ ] All API keys filled in `.env.docker`
- [ ] Reverse proxy (Nginx + HTTPS) in front of Streamlit
- [ ] Backup retention configured + tested
- [ ] Healthcheck passing
- [ ] Logs rotating (Docker log-driver)
