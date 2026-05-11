# ═══════════════════════════════════════════════════════════════════════════
# Market Analysis AI — v6.0 — Multi-stage Dockerfile
# ═══════════════════════════════════════════════════════════════════════════
# Stage 1: builder — installa Poetry + dipendenze, compila wheel
# Stage 2: runtime — immagine slim con solo il necessario
# ═══════════════════════════════════════════════════════════════════════════

FROM python:3.11-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

# Dipendenze build (compilatori C per numpy/scipy/duckdb)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libffi-dev \
        libssl-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN pip install "poetry==${POETRY_VERSION}"

WORKDIR /build

# Copia solo i file di dependency management per massimizzare la cache Docker
COPY pyproject.toml ./
COPY poetry.lock* ./

# Installa solo le dipendenze di runtime (niente dev)
RUN poetry install --only main --no-root

# ═══════════════════════════════════════════════════════════════════════════
# Runtime stage
# ═══════════════════════════════════════════════════════════════════════════
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOME=/app \
    LOG_FORMAT=json \
    LOG_LEVEL=INFO

# Dipendenze runtime (weasyprint + TA-lib richiedono librerie di sistema)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        curl \
        wget \
    && rm -rf /var/lib/apt/lists/*

# User non-root per sicurezza
RUN groupadd -r app && useradd -r -g app -d /app -s /bin/bash app

WORKDIR ${APP_HOME}

# Copia site-packages dallo stage builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Codice applicativo
COPY --chown=app:app shared ./shared
COPY --chown=app:app engine ./engine
COPY --chown=app:app personal ./personal
COPY --chown=app:app bridge ./bridge
COPY --chown=app:app presentation ./presentation
COPY --chown=app:app scripts ./scripts
COPY --chown=app:app config ./config
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app pyproject.toml ./

# Directory runtime montate come volumi
RUN mkdir -p db data/backups logs && chown -R app:app db data logs

USER app

# Healthcheck: Streamlit expose su 8501
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD wget --quiet --spider http://localhost:8501/_stcore/health || exit 1

# Default: avvia la dashboard engine. Override via docker-compose per scheduler.
CMD ["streamlit", "run", "presentation/dashboard_engine/app.py", \
     "--server.address=0.0.0.0", "--server.port=8501"]
