# ═══════════════════════════════════════════════════════════════════════════
# Market Analysis AI — v6.0 — Makefile
# ═══════════════════════════════════════════════════════════════════════════
# Target richiesti dalla Fase 0 DoD: setup, test, lint, type-check, run, backup
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: help setup install lint format type-check test test-fast coverage \
        run run-engine run-personal backup migrate clean \
        docker-build docker-run docker-logs docker-backup \
        pre-commit security-check

help:  ## Mostra questo help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ─── Setup ─────────────────────────────────────────────────────────────────
setup: install migrate  ## Installa dipendenze + migra database
	@echo "✓ Setup completato."

install:  ## Installa dipendenze Poetry
	poetry install --with dev
	poetry run pre-commit install

migrate:  ## Applica migrations DuckDB + SQLite
	poetry run python -c "from shared.db.duckdb_migrator import run_pending_migrations; run_pending_migrations()"
	@echo "✓ Migrations applicate."

# ─── Code quality ──────────────────────────────────────────────────────────
lint:  ## Esegue ruff check
	poetry run ruff check .

format:  ## Formatta codice con ruff
	poetry run ruff format .
	poetry run ruff check --fix .

type-check:  ## Esegue mypy in modalità strict
	poetry run mypy --strict shared engine personal bridge

security-check:  ## Esegue bandit + safety
	poetry run bandit -r shared engine personal bridge -ll
	poetry run safety check --full-report

# ─── Testing ───────────────────────────────────────────────────────────────
test:  ## Esegue tutti i test
	poetry run pytest

test-fast:  ## Solo test veloci (esclude slow, integration, benchmark)
	poetry run pytest -m "not slow and not integration and not benchmark"

coverage:  ## Test con coverage (Regola 10: target ≥ 80%)
	poetry run pytest --cov --cov-report=term-missing --cov-report=html --cov-fail-under=80
	@echo "✓ Report coverage in htmlcov/index.html"

# ─── Run ───────────────────────────────────────────────────────────────────
run: run-engine  ## Alias per run-engine

run-engine:  ## Avvia dashboard engine (analisi mercato)
	poetry run streamlit run presentation/dashboard_engine/app.py

run-personal:  ## Avvia dashboard personal (finanza personale)
	poetry run streamlit run presentation/dashboard_personal/app.py --server.port 8502

scheduler:  ## Avvia scheduler in foreground
	poetry run python scripts/run_scheduler.py

# ─── Operazioni di manutenzione ────────────────────────────────────────────
backup:  ## Backup manuale DuckDB + SQLite
	poetry run python scripts/backup.py

retention:  ## Pulizia dati oltre retention policy
	poetry run python scripts/duckdb_retention.py

# ─── Pre-commit ────────────────────────────────────────────────────────────
pre-commit:  ## Esegue pre-commit su tutti i file
	poetry run pre-commit run --all-files

# ─── Pulizia ───────────────────────────────────────────────────────────────
clean:  ## Rimuove artefatti temporanei (non tocca db/ né data/)
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "✓ Pulizia completata."

# ─── Docker ────────────────────────────────────────────────────────────────
docker-build:  ## Build immagine Docker
	docker compose build

docker-run:  ## Avvia stack Docker completo
	docker compose up -d

docker-logs:  ## Mostra logs dei container
	docker compose logs -f

docker-stop:  ## Ferma stack Docker
	docker compose down

docker-backup:  ## Backup dal container
	docker compose exec market_ai_app python scripts/backup.py
