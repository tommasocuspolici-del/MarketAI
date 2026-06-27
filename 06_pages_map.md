# 04 — Guida Sessioni Claude Code Opus 4.8

## Template Prompt di Apertura (copiare all'inizio di ogni sessione)

```
Ciao. Leggi completamente CLAUDE.md prima di scrivere qualsiasi codice.
Se ci sono file .claude/ referenziati, caricali con @ quando necessario.

=== SESSIONE N — [nome sessione] ===

Contesto ambiente:
- Progetto in: %APPDATA%\MarketAI\
- Python: 3.12.10 (venv Poetry — NON usare 3.14.x di sistema)
- poetry run pytest -m regression → [N passed / 0 failed] ← eseguito ADESSO

Task di questa sessione:
[descrizione specifica]

File da creare/modificare:
- [file1.py] → [cosa fare]
- [file2.py] → [cosa fare]

NON toccare:
- [lista file protetti]
- Dipendenze pinnate: yfinance==0.2.54, websockets, pandera

Definition of Done:
□ [criterio 1]
□ [criterio 2]
...

Inizia con: poetry run pytest -m regression -q --tb=short
Poi procedi con il task.
```

---

## Regola Gate di Regressione (INVIOLABILE)

**Prima di QUALSIASI modifica a qualsiasi file:**
```bash
poetry run pytest -m regression -q --tb=short
```
- **0 failed** → si può procedere
- **≥ 1 failed** → STOP. Indagare prima di toccare qualsiasi cosa.
- Il gate vale anche se la sessione precedente ha lasciato tutto funzionante.

---

## Definition of Done Template (per ogni sessione)

```
□ File richiesti creati/modificati secondo le specifiche
□ Type hints completi (mypy --strict: 0 errors sui nuovi file)
□ Docstring in inglese su tutte le funzioni pubbliche
□ Test scritti per ogni funzione pubblica
□ pytest -m regression: 0 failed (GATE — verificare come ULTIMO step)
□ Nessuna regressione su pagine esistenti
□ Layer boundaries rispettati (engine/personal non si importano)
□ Nessun print() introdotto
□ Nessun magic number introdotto (tutto in OP_CONFIG o YAML)
□ Nessuna API key nel codice (sempre da .env)
```

---

## Workflow Sessione Standard

### 1. Apertura (2-3 minuti)
1. `poetry run pytest -m regression -q` → 0 failed
2. `poetry env info` → Python 3.12.x confermato
3. Leggere CLAUDE.md + file .claude/ pertinenti alla sessione
4. Identificare file da creare/modificare e file protetti

### 2. Implementazione (1-1.5 ore)
- Creare/modificare file ONE AT A TIME
- Dopo ogni file: `poetry run python -c "import <modulo>"` (quick smoke test)
- Mai lasciare file a metà in stato di errore di import

### 3. Test (15-20 minuti)
- Scrivere test PRIMA di procedere al modulo successivo
- `pytest tests/path/to/new_test.py -v`
- `pytest -m regression -q` — gate finale

### 4. Chiusura (5 minuti)
- Commit con messaggio Conventional Commits
- `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- Aggiornare CLAUDE.md se necessario (nuovi moduli, fix)

---

## Pattern Sessioni per Tipo di Task

### Nuovo Modulo (engine o personal)
```
1. Verificare layer corretto
2. Verificare DB corretto (DuckDB vs SQLite)
3. Creare file con ABC/interfaccia prima
4. Implementare metodi uno alla volta
5. Scrivere test SUBITO dopo ogni metodo
6. Aggiornare __init__.py e __all__
```

### Nuova Pagina Dashboard
```
1. Copiare template pagina esistente simile
2. require_auth() come prima riga
3. @st.cache_data con CACHE_TTL corretti
4. Bottone "🔄 Aggiorna" in alto a destra
5. pragma: no cover su import (non testare UI direttamente)
6. Nessun valore hardcoded (tutto da OP_CONFIG)
```

### Migrazione Schema DuckDB
```
1. NON toccare il DB direttamente
2. Creare: shared/db/migrations/duckdb/YYYYMMDD_NNN_descrizione.sql
3. DuckDBMigrator.apply_pending() lo applica all'avvio
4. Testare idempotenza (applicare due volte non deve dare errori)
```

### Bug Fix
```
1. Scrivere test che FALLISCE riproducendo il bug (test prima del fix)
2. Applicare fix minimo
3. Verificare test passa
4. pytest -m regression: 0 failed
5. Commit: fix: descrizione concisa del bug
```

---

## Comandi Utili Durante la Sessione

```bash
# Verificare import funziona
poetry run python -c "from engine.analytics.forecasting.ensemble_predictor import EnsemblePredictor; print('OK')"

# Type check su file specifico
poetry run mypy --strict engine/analytics/forecasting/new_module.py

# Lint su file specifico
poetry run ruff check engine/analytics/forecasting/new_module.py

# Coverage su modulo specifico
poetry run pytest tests/engine/forecasting/ --cov=engine/analytics/forecasting --cov-report=term-missing

# Mutation testing (WSL only, non Windows)
mutmut run --paths-to-mutate engine/market_data/currency_converter.py

# Vedere test regression (quali sono)
poetry run pytest -m regression --collect-only -q
```

---

## Sessioni Pianificate (v11→v15)

| Fase | Versione | Contenuto | Sessioni |
|---|---|---|---|
| v11 | Infrastruttura | Installer, Management UI, CLAUDE.md v2 | 8 sessioni (18/08→06/09/2026) |
| v12 | Consolidamento | Data Provider Plugin, Logging JSON, CI/CD, MkDocs | 5 sessioni |
| v13 | Modellistica | Ensemble, Quantile, FeatureBuilder, Fan chart | 6 sessioni |
| v14 | Avanzata | N-BEATS (CPU), Backtesting realistico, FastAPI, Metriche | 7 sessioni |
| v15 | UI Native | pywebview, Persistenza sessioni, Drift detection, EXE | 7 sessioni |

**Stato corrente:** Pianificazione v11 (completata 15/06→17/08/2026). Implementazione dal 18/08/2026.

---

## Anti-Pattern da Evitare nelle Sessioni

```
❌ Sessione Opus senza gate regression iniziale
❌ Modificare pyproject.toml fuori da sessioni pianificate
❌ management_ui.py che importa engine/personal/shared
❌ Installer che usa "python" senza specificare 3.12
❌ PAT GitHub hardcoded in codice o in config JSON
❌ Backup che include .venv/
❌ Schema DuckDB modificato senza migration SQL
❌ Feature DL (N-BEATS, LSTM) abilitata di default
❌ PyTorch con CUDA/ROCm (sempre CPU)
❌ Sessione > 2 ore (preferire sessioni brevi e focalizzate)
```

---

## Riferimenti vault correlati

- [[Vibecoding workflow]] — workflow completo con Recovery da Gate Fallito
- [[08_bugfix_protocol]] — protocollo completo per errori segnalati dall'utente
