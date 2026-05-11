# Quickstart — 5 minutes

## Prerequisites

- Python 3.11+
- Poetry 1.8+
- Free API keys: [Finnhub](https://finnhub.io), [Alpha Vantage](https://alphavantage.co)

## Steps

### 1. Clone and install

```bash
git clone https://github.com/yourusername/market-ai.git
cd market-ai
poetry install
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in:
#   FINNHUB_API_KEY=your_key
#   ALPHA_VANTAGE_KEY=your_key
#   STREAMLIT_AUTH_ENABLED=false  (true in production)
```

### 3. Initialize databases

```bash
poetry run python -m scripts.init_db
```

This applies all DuckDB migrations and creates SQLite tables for the
personal layer.

### 4. Download initial market data

```bash
poetry run python scripts/bulk_fred_download.py
```

Downloads ~600 macroeconomic series from FRED. Takes about 10 minutes
on the free tier (rate-limited).

### 5. Launch the dashboards

```bash
# Terminal 1 — engine dashboard
poetry run streamlit run presentation/dashboard_engine/app.py

# Terminal 2 — personal dashboard
poetry run streamlit run presentation/dashboard_personal/app.py --server.port 8502
```

Open:

- http://localhost:8501 — Engine Dashboard (14 pages)
- http://localhost:8502 — Personal Dashboard (9 pages)

## Verify Everything Works

```bash
make lint        # ruff → 0 warnings
make type-check  # mypy --strict → 0 errors
make test        # pytest → 0 failed
```

If you see `585+ passed`, you're set.

## Next

- [Setup from Zero (full guide)](setup.md) — for a deeper walkthrough
- [Configuration](configuration.md) — feature flags, rate limits, retention
- [Architecture Overview](../architecture/overview.md) — understand what's where
