# Setup from Zero

Detailed walkthrough for first-time setup. For a 5-minute guide see
[Quickstart](quickstart.md).

## Prerequisites

```bash
# Python 3.11+
pyenv install 3.11.9
pyenv local 3.11.9

# Poetry 1.8+
curl -sSL https://install.python-poetry.org | python3 -

# Optional: Docker for containerized deployment
# https://docs.docker.com/get-docker/

# Optional: Ollama for LLM-based narratives (Phase 8 feature)
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull mistral:7b
```

## Repository Setup

```bash
git clone https://github.com/yourusername/market-ai.git
cd market-ai
poetry install --with dev
poetry shell
```

## Environment Configuration

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Required | Description |
|----------|----------|-------------|
| `FINNHUB_API_KEY` | Yes | Free at https://finnhub.io |
| `ALPHA_VANTAGE_KEY` | Yes | Free at https://alphavantage.co |
| `FRED_API_KEY` | Optional | Improves rate limit |
| `SEC_EDGAR_USER_AGENT` | Yes | "Your Name (your.email@example.com)" |
| `STREAMLIT_AUTH_ENABLED` | Yes | `false` for local, `true` for prod |
| `STREAMLIT_AUTH_PASSWORD_HASH` | Prod | SHA-256 of your password |

Generate password hash:

```bash
python -c "import hashlib; print(hashlib.sha256(b'YourPassword').hexdigest())"
```

## Database Initialization

```bash
poetry run python -m scripts.init_db
```

Applies all DuckDB migrations from `shared/db/migrations/duckdb/` and
creates SQLite tables for personal layer.

## Bulk Data Download

```bash
poetry run python scripts/bulk_fred_download.py
```

Downloads ~600 macro series from FRED. Takes ~10 min on free tier.

## Verify Installation

```bash
make lint        # 0 warnings expected
make type-check  # 0 errors expected
make test        # 585+ tests passing
```

## Next: [Configuration](configuration.md)
