# Workflow Vibecoding — Claude Code Pro

Questo documento definisce il flusso operativo per lo sviluppo di MarketAI con Claude Code Pro (Opus 4.8). L'obiettivo è massimizzare la produttività in sessioni brevi (1–2h) mantenendo zero regressioni.

---

## 🔴 Gate di Regressione — INVIOLABILE

**Prima di QUALSIASI modifica a QUALSIASI file:**
```bash
poetry run pytest -m regression -q --tb=short
```
- **0 failed** → si può procedere
- **≥ 1 failed** → STOP immediato, indagare prima di toccare il codice
- Questo vale anche all'inizio di ogni sessione nuova, anche se la precedente è andata bene

---

## Principi Guida

- **Sessioni brevi e focalizzate:** 1–2 ore per sessione, un obiettivo chiaro per sessione
- **Prompt ricchi di contesto:** Includere sempre `CLAUDE.md` + file `.claude/` pertinenti
- **Test-first:** Scrivere test che falliscono PRIMA del fix/feature
- **Gate obbligatorio:** Nessun commit senza `pytest -m regression` verde
- **Dipendenze pinnate:** Non aggiornare `yfinance`, `websockets`, `pandera` mai

---

## Flusso Operativo Passo-Passo

### 1. Apertura Sessione (3-5 minuti)

```bash
# Spostarsi nella cartella del progetto
cd %APPDATA%\MarketAI\

# Verificare ambiente Python
poetry env info          # → Python 3.12.x (NON 3.14.x)

# Gate obbligatorio
poetry run pytest -m regression -q --tb=short   # → 0 failed

# Aprire il file di sessione dal vault
```

### 2. Preparazione Prompt per Opus

Copiare sempre il template da `.claude/04_session_guide.md` e riempire:
- Task specifico della sessione
- File da creare/modificare
- File protetti (NON toccare)
- Definition of Done

**File sempre inclusi nel prompt:**
```
CLAUDE.md                          ← sempre
.claude/02_architecture.md         ← se lavori su moduli
.claude/03_conventions.md          ← se aggiungi codice
.claude/07_data_pipeline.md        ← se tocchi dati o DB
```

### 3. Durante la Sessione

- **Un file alla volta:** Creare/modificare → testare → procedere al prossimo
- **Quick smoke test dopo ogni file:** `poetry run python -c "import <modulo>"`
- **Mai lasciare import rotti** tra un file e l'altro
- **Controllare layer boundaries:** engine ↔ personal solo via bridge

### 4. Chiusura Sessione

```bash
# Gate finale — OBBLIGATORIO
poetry run pytest -m regression -q --tb=short   # → 0 failed

# Tipo + lint
poetry run mypy --strict <file_modificati>
poetry run ruff check .

# Commit
git add -A
git commit -m "feat: descrizione concisa"
# Claude Opus aggiunge automaticamente:
# Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

# Push (da Management UI o manuale)
git push origin main
```

### 5. Aggiornamento Vault

Dopo ogni sessione che introduce moduli nuovi o cambia l'architettura:
- Aggiornare il file del modulo in `Modules/`
- Aggiornare `CLAUDE.md` se ci sono nuovi import o pattern
- Aggiornare il `Glossary` se ci sono nuovi termini

---

## Checklist per Ogni Sessione

```
□ Gate regressione: 0 failed
□ Python env: 3.12.x confermato
□ CLAUDE.md letto (o caricato in Claude Code)
□ Obiettivo sessione chiaramente definito
□ File protetti identificati
□ Task implementati
□ Test scritti per ogni funzione pubblica
□ Gate finale: 0 failed
□ Commit con messaggio Conventional Commits
□ Vault aggiornato (se necessario)
```

---

## Gestione Errori Comuni

| Situazione | Azione |
|---|---|
| Test falliti a inizio sessione | STOP. Identificare causa prima di procedere |
| `Poetry usa Python 3.14` | `poetry env use "...\Python312\python.exe"` |
| Import circolare introdotto | Rivedere layer boundaries, usare bridge |
| Coverage scesa sotto 89% | Scrivere test prima di proseguire |
| pyproject.toml modificato per sbaglio | `git checkout HEAD -- pyproject.toml` |

---

## Anti-Pattern da Evitare

```
❌ Sessione senza gate regressione iniziale
❌ Sessione > 2 ore (meglio dividere)
❌ Modificare pyproject.toml fuori sessioni pianificate
❌ management_ui.py con import engine/personal/shared
❌ Installer che usa "python" invece di esplicitare 3.12
❌ DL (N-BEATS) con CUDA/GPU (sempre CPU su questo hardware)
❌ Schema DuckDB modificato senza migration SQL
❌ Feature sperimentale abilitata di default in feature_flags.yaml
❌ "except Exception: pass" in qualsiasi file non-test
❌ print() in produzione (usare get_logger)
```

---

## 🔧 Recovery da Gate Fallito

Quando `pytest -m regression` mostra ≥ 1 failed a inizio sessione — prima di toccare qualsiasi file:

### Step 1 — Isolare l'origine

```bash
# Mostrare esattamente quale test fallisce e perché
poetry run pytest -m regression -v --tb=long

# Identificare il file coinvolto dal traceback
# Controllare se era già rotto prima delle ultime modifiche
git stash            # nascondere le modifiche locali non committate
poetry run pytest -m regression -q
git stash pop        # ripristinare
```

Se i test falliscono **anche dopo `git stash`** → il problema era preesistente, non introdotto dall'ultima sessione. Investigare la causa radice.

### Step 2 — Identificare il commit responsabile

```bash
# Ultime 5 sessioni
git log --oneline -5

# Trovare quando il test ha smesso di passare (bisect)
git bisect start
git bisect bad HEAD              # commit attuale è bad
git bisect good <commit-ok>      # ultimo commit noto come good
# git bisect esegue checkout automatici → testare a ogni step:
poetry run pytest -m regression -q
git bisect good   # o git bisect bad
# Alla fine: git bisect reset
```

### Step 3 — Rollback selettivo

```bash
# Rollback di un singolo file (senza toccare gli altri)
git checkout HEAD -- engine/market_data/providers/registry.py

# Rollback di un'intera cartella
git checkout HEAD -- engine/market_data/providers/

# Rollback completo all'ultimo commit (ATTENZIONE: perde le modifiche non committate)
git reset --hard HEAD
```

### Step 4 — Fix e ripartenza

```bash
# Dopo aver identificato e rollbackato il file problematico:
poetry run pytest -m regression -q   # → 0 failed
# Solo ora procedere con la sessione
```

---

## 📋 Regole Aggiornamento Vault

Dopo ogni sessione che tocca uno dei seguenti tipi di modifica, aggiornare il vault:

### Tabella: tipo di modifica → file vault da aggiornare

| Tipo di modifica | File vault da aggiornare |
|---|---|
| Nuovo modulo in `engine/analytics/` | `Modules/<NomeModulo>.md` (creare se non esiste) · `Architecture/Market Analysis Engine.md` |
| Nuovo modello di previsione | `Modules/<NomeModello>.md` · `Modules/Forecasting Engine Map.md` · `Modules/Model Registry.md` |
| Nuovo provider dati | `Modules/Data Provider System.md` · `CLAUDE.md` sezione "Moduli Chiave" |
| Nuovo endpoint FastAPI | `API/FastAPI Backend.md` · `CLAUDE.md` sezione "FastAPI" |
| Bug fixato | `CLAUDE.md` sezione "Bug Noti e Fix Applicati" (tabella B-ID) |
| Nuova migration DuckDB | `Architecture/Data Flow.md` sezione "Schema DuckDB" |
| Nuova pagina dashboard | `CLAUDE.md` sezione "Mappa Pagine" |
| Nuova dipendenza in pyproject.toml | `CLAUDE.md` sezione "Dipendenze Pinnate" (se critica) |
| Nuova feature flag | `CLAUDE.md` + `Configuration/Config Files.md` |
| Nuovo file `.claude/` | `CLAUDE.md` sezione "Session Startup" + `index/Home.md` |

### Chi aggiorna il vault

- **Claude Opus (in sessione):** aggiorna `CLAUDE.md` e i file `.claude/` pertinenti
- **L'utente (post-sessione):** verifica che i file `Modules/` e `Architecture/` riflettano la realtà del codice
- **Regola:** Se il vault non viene aggiornato entro 24h dalla sessione, il rischio di deriva vault-codice aumenta significativamente

### Template aggiornamento Modules/

Se il modulo è nuovo (non esiste ancora un file):
```
□ Creare Modules/<NomeModulo>.md
□ Includere: Panoramica · File sorgente · Interfaccia pubblica · Test · Anti-pattern · Relazioni
□ Aggiungere link [[]] ai moduli correlati
□ Aggiornare Home.md sezione "Moduli documentati"
```

Se il modulo esiste ma è cambiato:
```
□ Aggiornare firma API (metodi aggiunti/rimossi)
□ Aggiornare la sezione "Test" se ci sono nuovi test
□ Aggiornare "Bug noti" se il fix ha rivelato comportamenti non documentati
□ Aggiornare Glossary se ci sono nuovi termini
```
