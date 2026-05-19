# MarketAI v1.0 — Guida Installazione

**MarketAI Professional Edition** — piattaforma di analisi quantitativa dei mercati e gestione patrimoniale personale.

---

## Requisiti di Sistema

| Componente | Minimo | Raccomandato |
|------------|--------|--------------|
| Python | 3.11 | 3.12 |
| RAM | 4 GB | 8+ GB |
| Disco | 2 GB | 5+ GB |
| SO | Windows 10 / macOS 12 / Ubuntu 20.04 | Windows 11 / macOS 14 / Ubuntu 22.04 |

> **LLM (opzionale):** Per abilitare l'analisi testuale con Ollama, servono 5+ GB RAM aggiuntivi e 4+ GB disco.

---

## Installazione Rapida

```bash
# 1. Clona il repository
git clone https://github.com/your-username/MarketAI.git
cd "MarketAI 1.0"

# 2. Installa Poetry (se non già installato)
# Windows: winget install Python.Poetry
# macOS/Linux: curl -sSL https://install.python-poetry.org | python3 -

# 3. Esegui l'installer
python scripts/install.py
```

L'installer esegue automaticamente:
1. Verifica Python 3.11+ e Poetry
2. Installa tutte le dipendenze (`poetry install`)
3. Crea `.env` dall'esempio se non esiste
4. Inizializza DuckDB e SQLite con le migration
5. Verifica l'installazione (quality gate)

---

## Configurazione API Key

Apri `.env` (creato dall'installer) e configura le chiavi:

```bash
# API gratuite — ottenibili in 5 minuti
FRED_API_KEY=xxx            # https://fred.stlouisfed.org/docs/api/api_key.html
FINNHUB_API_KEY=xxx         # https://finnhub.io (free tier: 60 req/min)
ALPHA_VANTAGE_KEY=xxx       # https://www.alphavantage.co (free tier: 5 req/min)
SEC_EDGAR_USER_AGENT="Nome Cognome email@example.com"

# Opzionali
BLS_API_KEY=                # https://data.bls.gov/registrationEngine/
ETORO_API_KEY=xxx           # se usi eToro
ETORO_USER_KEY=xxx
```

> **Nota:** MarketAI funziona anche senza chiavi API usando i dati già in cache. Le chiavi aumentano la frequenza di aggiornamento.

---

## Avvio

### Metodo 1 — Launcher (raccomandato)

```bash
python launcher.py
```

Il launcher apre il browser automaticamente.

### Metodo 2 — Streamlit diretto

```bash
poetry run streamlit run app_unified.py
```

Poi apri: http://localhost:8501

---

## Struttura Navigazione

Il dashboard è organizzato in 7 sezioni:

| Sezione | Pagine | Descrizione |
|---------|--------|-------------|
| 📡 SISTEMA | S0–S2 | Health, pipeline status, impostazioni |
| 🌍 MACRO & CICLO | M1–M7 | Macro FRED, yield curve, labour, P/E, IB |
| 📊 MERCATI | K1–K5 | Market overview, equity, bonds, commodity |
| 🔬 ANALISI QUANT | Q1–Q11 | VIX, sentiment, correlazioni, walk-forward |
| 📰 NEWS & IB | N1–N2 | Feed notizie live, analisi sentiment |
| ⚙️ STRATEGIE | T1–T3 | Backtesting, stress test, alert |
| 💼 PERSONAL | P1–P9 | Patrimonio, portafoglio, cashflow, fiscale |

---

## Inizializzazione Database

Se vuoi inizializzare il DB manualmente:

```bash
python scripts/init_database.py
```

Per reinizializzare da zero (attenzione: cancella i dati):

```bash
python scripts/init_database.py --force
```

---

## LLM Opzionale (Ollama)

MarketAI funziona completamente senza LLM. L'LLM migliora la qualità dei commenti testuali (narrativa mercato, analisi notizie).

### Installazione Ollama

**Windows:**
```
winget install Ollama.Ollama
```

**macOS:**
```bash
brew install ollama
```

**Linux:**
```bash
curl -fsSL https://ollama.ai/install.sh | sh
```

### Download modello

```bash
python scripts/download_models.py
```

Il script rileva automaticamente l'hardware e suggerisce il modello ottimale:
- **mistral:7b-q4** (raccomandato) — 4.1 GB, richiede 5 GB RAM
- **phi3:mini** (compatto) — 2.3 GB, richiede 4 GB RAM

### Attivazione

1. Avvia Ollama: `ollama serve`
2. In MarketAI: **S2_Settings → LLM → Master Switch → ON**

---

## Scheduler Automatico

Lo scheduler aggiorna i dati ogni 4 ore (lun–ven):

```bash
# Avvio in background
poetry run python scripts/run_scheduler.py

# Test senza scrivere dati
poetry run python scripts/run_scheduler.py --dry-run
```

Per il primo caricamento dati, usa i bottoni "📥 Carica" nelle pagine:
- **M3** Labour Market → `📥 Carica da FRED`
- **M5** Economic Surprise → `📥 Carica consensus`
- **M7** IB Consensus → `📥 Aggiorna previsioni`
- **N1** News Feed → `📥 Fetch ora`

---

## Verifica Installazione

```bash
# Quality gate completo
poetry run python scripts/quality_gate.py --skip-mypy

# Test suite
poetry run pytest tests/ --tb=short -q

# Health check
# Apri S0_Health nel dashboard per il check visuale
```

---

## Aggiornamento

```bash
git pull origin main
poetry install          # aggiorna dipendenze
python scripts/init_database.py  # applica nuove migration
```

---

## Struttura Directory

```
MarketAI 1.0/
├── app_unified.py          ← Entry point principale (Streamlit)
├── launcher.py             ← Launcher con splash screen
├── INSTALL.md              ← Questa guida
├── .env.example            ← Template configurazione
├── config/                 ← YAML configurazione
│   ├── feature_flags.yaml
│   ├── cache_ttl.yaml
│   └── modules_registry.yaml
├── engine/                 ← Analisi quantitativa
├── personal/               ← Dati patrimonio personale
├── presentation/           ← UI Streamlit (read-only)
├── shared/                 ← Database, logger, resilience
├── scripts/                ← Utility (install, scheduler, QA)
├── tests/                  ← Test suite (3200+ test)
└── docs/                   ← Documentazione MkDocs
```

---

## Risoluzione Problemi

### "No module named 'duckdb'"
```bash
poetry install
```

### "Port 8501 already in use"
```bash
# Termina sessioni precedenti
python launcher.py  # il launcher le chiude automaticamente
```

### "DB migration failed"
```bash
python scripts/init_database.py --force
```

### "Ollama not reachable"
```bash
ollama serve  # avvia il servizio Ollama
```

### "API key missing"
Configura le chiavi in `.env` (vedi sezione Configurazione sopra).

---

## Privacy & Sicurezza

- **Zero cloud LLM** — solo Ollama locale, nessun dato inviato a server esterni
- **Single user** — sistema per uso personale, nessun multi-tenancy
- **API key locali** — solo nel file `.env`, mai nel codice o nei log
- **Dati personali** — SQLite locale, non sincronizzato

---

*MarketAI v1.0 Production — ⚠️ Solo scopo informativo, non costituisce consulenza finanziaria.*
