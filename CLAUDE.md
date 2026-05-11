# CLAUDE.md — Istruzioni Operative per Claude Code
## MarketAI Professional Edition
### Versione 1.0 — Maggio 2026
### Baseline progetto: v7.1.1 (86 test passing)

> **LEGGERE INTEGRALMENTE ALL'INIZIO DI OGNI SESSIONE.**
> Questo file va aggiornato da Claude Code ad ogni modifica significativa al progetto.

---

## 0. CONTESTO GENERALE

MarketAI è una piattaforma professionale duale per:
- **Analisi quantitativa dei mercati** (engine layer)
- **Finanza personale** (personal layer)

L'utente **non ha esperienza di programmazione**. Tutto il codice viene scritto
da Claude Code. L'utente interagisce tramite linguaggio naturale e revisiona
i risultati. Claude Code è l'unico autore del codice.

**Architettura di riferimento:** ROADMAP_v6.md (32 convenzioni obbligatorie)
**Piano di sviluppo attivo:** ROADMAP_UNIFICATA_v2.md (v2.0, baseline v7.1.1)

---

## 1. AMBIENTE DI SVILUPPO

| Parametro | Valore |
|---|---|
| Sistema operativo | Windows 11 |
| Python | 3.12 |
| Package manager | Poetry |
| IDE disponibile | IDLE Python 3.12 (utente non programma direttamente) |
| Directory progetto | `C:\Q256254\Documenti\marketai\MarketAI1.0` |
| Git | Branch unico: `main` |
| Database DuckDB | ~1 GB, dati reali utente presenti |
| Docker | Non in uso (ambiente locale diretto) |
| Stato attuale | v7.1.1 — Migration 007 in corso, fix eToro API in corso |

> **Nota percorsi Windows:** Usare sempre `pathlib.Path` per la gestione dei
> percorsi. Mai stringhe con separatori hardcoded (`/` o `\`).

---

## 2. STRUTTURA DIRECTORY

```
C:\Q256254\Documenti\marketai\MarketAI1.0\
│
├── shared/
│   ├── types.py
│   ├── exceptions.py
│   ├── logger.py
│   ├── constants.py
│   ├── fx_service.py
│   ├── health.py
│   ├── metrics.py
│   ├── error_budget.py
│   ├── rate_limit_manager.py
│   ├── feature_flags.py
│   ├── backup_manager.py
│   └── db/
│       ├── duckdb_client.py
│       ├── duckdb_migrator.py
│       ├── sqlite_client.py
│       ├── dual_writer.py
│       └── migrations/
│           ├── duckdb/          ← script SQL versionati
│           └── sqlite/          ← gestite da Alembic
│
├── bridge/
│   ├── api_contracts.py
│   ├── engine_client.py
│   └── personal_client.py
│
├── engine/
│   ├── market_data/
│   ├── market_registry/
│   ├── analytics/
│   ├── backtesting/
│   ├── stress_testing/
│   ├── forecasting/
│   └── alerts/
│
├── personal/
│   ├── portfolio/
│   ├── cashflow/
│   ├── networth/
│   ├── goals/
│   ├── investor_profile/
│   ├── wealth_scenarios/
│   ├── tax/
│   ├── allocator/
│   └── alerts/
│
├── presentation/
│   ├── ui/
│   │   ├── auth.py
│   │   ├── theme.py
│   │   ├── layout.py
│   │   └── components/
│   ├── dashboard_engine/pages/    ← pagine E0–E14 (in migrazione a S/M/K/Q/T)
│   └── dashboard_personal/pages/ ← pagine P1–P9
│
├── tests/
├── config/
├── scripts/
├── docs/
├── .env
├── .env.example
├── pyproject.toml
├── Makefile
├── CHANGELOG.md
├── ROADMAP_v6.md
├── ROADMAP_UNIFICATA_v2.md
└── CLAUDE.md                      ← questo file
```

---


---

## 4. CONVENZIONI OBBLIGATORIE (32 REGOLE — v6.0)

Tutte e 32 le regole sono **attive senza eccezioni**. Riportate qui per
riferimento rapido; il testo completo è in `ROADMAP_v6.md`.

### Architettura

| # | Regola | Sintesi |
|---|---|---|
| 1 | LINGUA | Codice in inglese. Commenti logici in italiano. Docstring in inglese. |
| 2 | SRP | Ogni modulo ha una sola responsabilità. Nessun file supera 400 righe. |
| 3 | TIPI | Type hints Python ovunque. Nessuna funzione senza annotazione completa. |
| 4 | IMPORT | Import assoluti. Nessun import circolare. `__init__.py` con `__all__`. |
| 5 | ERRORI | Nessun `except` generico. Eccezioni custom da `shared/exceptions.py`. |
| 6 | LOGGING | Solo `structlog` da `shared/logger.py`. Mai `print()` in produzione. |
| 7 | COSTANTI | In `shared/constants.py` o YAML. Zero magic number. |
| 8 | MATEMATICA | Sempre numpy/scipy. Mai `float` nativo per finanza. |
| 9 | DATI | Ogni DataFrame ha schema Pandera esplicito. Zero dtype `"object"`. |
| 10 | TEST | Ogni funzione pubblica ha almeno un test unitario. Coverage ≥ 80%. |

### Dati e Persistenza

| # | Regola | Sintesi |
|---|---|---|
| 11 | ASYNC | Chiamate rete sempre async/await (aiohttp). Mai `requests` in produzione. |
| 12 | DATA_PIPELINE | fetch → clean → validate → duckdb_write → cache → return. INVARIABILE. |
| 13 | DUCKDB | Dati storici massivi: DuckDB. Dati relazionali/transazionali: SQLite. |
| 14 | CLEAN_FIRST | Ogni dato grezzo passa per `DataCleaner` prima della validazione Pandera. |
| 15 | SICUREZZA | Nessuna API key nel codice. `.env` + `python-dotenv`. Zero secret nei log. |
| 16 | VERSIONE | Ogni modulo espone `__version__ = "X.Y.Z"`. |
| 17 | COMMIT | Conventional Commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `perf:`, `chore:`. |

### Layer e Comunicazione

| # | Regola | Sintesi |
|---|---|---|
| 18 | VALUTE | Ogni importo ha `Currency` esplicita. Conversione via `shared/fx_service.py`. |
| 19 | DATE | Nessuna data naive. UTC internamente, locale in UI. |
| 20 | UI | Zero valori hardcoded nei componenti. Tutti da `DESIGN_TOKENS`. |
| 21 | LAYER | `engine/` ↔ `personal/` SOLO tramite `bridge/api_contracts.py`. |
| 22 | PROFILO | Ogni suggerimento filtrato da `InvestorProfile`. Zero eccezioni. |

### Qualità Analitica

| # | Regola | Sintesi |
|---|---|---|
| 23 | BACKTEST | VectorBT. Sempre: commissioni, slippage, look-ahead bias check. |
| 24 | STRESS_TEST | Scenari storici + scenari sintetici forward-looking. Mai solo storico. |
| 25 | LATENCY | Dati real-time ≤ 60s. WebSocket dove disponibile. |
| 26 | DATA_QUALITY | Ogni serie ha `DataQualityReport`. Score < 0.5 → warning, escluso da calcoli critici. |

### Nuove — v6.0

| # | Regola | Sintesi |
|---|---|---|
| 27 | DUCKDB_MIGRATIONS | Script SQL in `shared/db/migrations/duckdb/YYYYMMDD_NNN_descrizione.sql`. Mai modificare schema manualmente. |
| 28 | RATE_BUDGET | Ogni fetcher usa `RateLimitManager`. Nessun bypass. |
| 29 | FEATURE_FLAGS | Funzionalità sperimentali/costose → `config/feature_flags.yaml`. Default: `false`. |
| 30 | ERROR_BUDGET | SLA: latenza P95 ≤ 2s, uptime scheduler ≥ 99%. Error rate > 10% → auto-sospensione. |
| 31 | DATA_RETENTION | DuckDB: prezzi 20a, macro 30a, sentiment 3a. SQLite: posizioni 10a. |
| 32 | AUTH_UI | Streamlit protetto da password. Mai deployare senza autenticazione. |

---

## 5. ANTI-PATTERN VIETATI

Claude Code non deve **mai** produrre codice che contenga questi pattern:

```python
# ❌ VIETATO — import cross-layer diretto
from personal.portfolio import something      # engine/ non importa da personal/
from engine.analytics import something        # personal/ non importa da engine/

# ❌ VIETATO — except generico
try:
    ...
except Exception:                            # usare eccezioni custom
    pass

# ❌ VIETATO — print in produzione
print("debug")                               # usare structlog

# ❌ VIETATO — float per finanza
price = 100.50                               # usare np.float64 o Decimal

# ❌ VIETATO — datetime naive
from datetime import datetime
dt = datetime.now()                          # usare pd.Timestamp con tz="UTC"

# ❌ VIETATO — API key nel codice
API_KEY = "sk-abc123"                        # usare .env + python-dotenv

# ❌ VIETATO — dati grezzi in DB senza pipeline
db.write(raw_data)                           # sempre: fetch→clean→validate→write

# ❌ VIETATO — loop Python su serie temporali
for i in range(len(df)):                     # usare numpy/VectorBT vettorizzato
    df.iloc[i]["close"] * 1.1

# ❌ VIETATO — schema DuckDB modificato manualmente
conn.execute("ALTER TABLE prices ADD COLUMN x")  # usare migration SQL

# ❌ VIETATO — fetch senza RateLimitManager
response = await aiohttp.get(url)            # sempre via RateLimitManager.acquire()

# ❌ VIETATO — colori hardcoded in UI
st.markdown('<p style="color: #FF0000">')    # usare DESIGN_TOKENS

# ❌ VIETATO — pathlib non usato su Windows
path = "shared/db/" + "file.db"             # usare pathlib.Path sempre
```

---

## 6. COMPORTAMENTO DI CLAUDE CODE

### 6.1 Ad ogni inizio di sessione

1. **Leggere** questo file `CLAUDE.md` integralmente.
2. **Leggere** `ROADMAP_UNIFICATA_v2.md` per capire lo stato corrente.
3. **Verificare** quale task è in corso dalla sezione "Stato Corrente".
4. **Comunicare** all'utente: task attivo, dipendenze non soddisfatte, rischi noti.
5. **Non scrivere codice** fino a quando il task non è chiaro.
6. **leggere il file .cloudignore** ed aggiornarlo se necessario

### 6.2 Durante lo sviluppo

- **Un modulo per sessione.** Non iniziare il modulo successivo senza DoD verificato.
- **Proporre prima di implementare** quando l'approccio non è ovvio: descrivere la soluzione e chiedere conferma all'utente.
- **Generare sempre il `DataQualityReport`** nei fetcher, senza aspettare che sia richiesto.
- **Scrivere test** a discrezione (prima o dopo il codice), ma la coverage ≥ 80% è obbligatoria prima di chiudere il task.
- **Correggere anti-pattern** trovati nel codice esistente se impediscono il funzionamento o violano le 32 regole; segnalare gli altri senza toccarli.
- **Refactorare file > 600 righe** (soglia pratica, non 400) solo se necessario per il task in corso.

### 6.3 Gestione delle migrazioni DuckDB

- Le migration già applicate **possono essere modificate solo con estrema cautela**
  (es. per correggere un bug critico), mai per aggiungere funzionalità.
- Per qualsiasi nuova modifica schema → creare sempre un **nuovo file** `YYYYMMDD_NNN_descrizione.sql`.
- Verificare sempre che il file usi `IF NOT EXISTS` e `IF EXISTS` per sicurezza.
- Comunicare all'utente prima di applicare qualsiasi migration su DB con dati reali.

### 6.4 Gestione degli errori e incertezze

- Se Claude Code non è sicuro dell'implementazione corretta: **proporre la soluzione
  principale, indicare le alternative in commento, e chiedere un parere all'utente.**
- Se un task dipende da un modulo non ancora implementato: **segnalarlo esplicitamente**
  e non procedere con mock silenziosi.
- Se viene trovato un bug non correlato al task in corso: **segnalarlo nel log della
  sessione** senza modificare il codice, salvo che sia critico per la sicurezza dei dati.

---

## 7. GIT E VERSIONING

### Convenzioni commit (Conventional Commits)

```
feat:     nuova funzionalità
fix:      correzione bug
refactor: refactoring senza cambio funzionalità
docs:     aggiornamento documentazione (CLAUDE.md, CHANGELOG, README)
test:     aggiunta/modifica test
perf:     ottimizzazione performance
chore:    manutenzione (dipendenze, config, migration)
```

**Esempi:**
```bash
git commit -m "feat(futures): add FuturesFetcher with roll_yield calculation"
git commit -m "fix(etoro): resolve API import position mapping error"
git commit -m "chore(db): apply migration 007 unified v2"
git commit -m "docs(claude): update current state to v7.2"
```

### Regole git

- **Branch:** sempre su `main`.
- **Commit atomici:** un commit per modulo/fix logico, non uno per file.
- **Mai committare:** `.env`, file `*.db`, `__pycache__/`, `*.pyc`, dati personali.
- **Claude Code fa il commit** al termine di ogni task verificato (test passing).
- Il messaggio commit deve referenziare il task della Roadmap se applicabile.

---

## 8. AGGIORNAMENTO DEI FILE DI PROGETTO

### Quando aggiornare `CHANGELOG.md`
- Ad ogni commit con prefisso `feat:` o `fix:` significativo.
- Formato:
  ```markdown
  ## [v7.2.0] — YYYY-MM-DD
  ### Added
  - FuturesFetcher con calcolo roll_yield, basis, open_interest
  ### Fixed
  - EtoroClient: mapping posizioni API corretto
  ```

### Quando aggiornare `ROADMAP_UNIFICATA_v2.md`
- Al completamento di ogni task della roadmap: cambiare `⬜` in `✅`.
- Al completamento di ogni settimana: aggiornare la sezione "Stato Baseline".
- Mai modificare le sezioni storiche già completate (solo aggiungere).

### Quando aggiornare `CLAUDE.md` (questo file)
- Quando cambiano le convenzioni o vengono aggiunte nuove regole.
- Quando lo stato del progetto cambia significativamente.
---

## 9. STANDARD DI CODICE

### 9.1 Struttura di un modulo tipo

```python
"""
Module docstring in English.

Describes what this module does, its responsibilities,
and any important constraints.
"""
from __future__ import annotations

# Standard library
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Third-party
import numpy as np
import structlog

# Internal — solo import dalla propria layer o da shared/bridge
from shared.exceptions import DataFetchError
from shared.logger import get_logger
from shared.rate_limit_manager import RateLimitManager

__version__ = "1.0.0"
__all__ = ["MyClass", "my_function"]

log = structlog.get_logger(__name__)


class MyClass:
    """One-line description.

    Longer description if needed.
    Regola XX: reference to relevant rule.
    """

    def __init__(self, param: str) -> None:
        self._param = param

    async def fetch(self, ticker: str) -> np.ndarray:
        """Fetch data for ticker.

        Args:
            ticker: Market ticker symbol with exchange suffix.

        Returns:
            Array of OHLCV values.

        Raises:
            DataFetchError: If the API call fails.
        """
        # TODO(v7.2): aggiungere supporto multi-exchange
        log.info("my_class.fetch_start", ticker=ticker)
        ...
```

### 9.2 Struttura log structlog

Formato: `modulo.azione` — tutto minuscolo con underscore.

```python
# Esempi corretti:
log.info("rate_limiter.acquired", source="finnhub", rpm=45)
log.info("duckdb_migrator.applied", version="20260615_007")
log.warning("data_quality.low_score", series_id="CPIAUCSL", score=0.43)
log.error("etoro_client.fetch_failed", error=str(e), ticker="AAPL")
```

### 9.3 Commenti inline

```python
# Commenti logici IN ITALIANO per spiegare il perché, non il cosa
# Calcolo yield spread: differenza tra rendimento 10Y e 3M per Estrella-Mishkin
spread = dgs10 - dgs3mo

# TODO(v7.3): aggiungere breakeven inflation come quarta componente
recession_prob = estrella_mishkin(spread)
```

### 9.4 TODO standard

```python
# TODO(v7.x): descrizione del miglioramento futuro
# FIXME(v7.x): descrizione del problema noto
# NOTE: spiegazione di una scelta non ovvia
```

### 9.5 DataQualityReport — obbligatorio in ogni fetcher

```python
from shared.db.data_quality import DataQualityReport

# Generare SEMPRE dopo il fetch, PRIMA di scrivere su DuckDB
quality_report = DataQualityReport.compute(df, series_id=series_id)
if quality_report.quality_score < 0.5:
    log.warning("fetcher.low_quality", series_id=series_id,
                score=quality_report.quality_score)
    # Non entrare nei calcoli critici senza approvazione
```

---

## 10. PRIORITÀ ASSOLUTE ATTUALI

In ordine di priorità:

1. **Fix eToro API** — risolvere problemi con `EtoroClient` e import posizioni.
   Moduli coinvolti: `personal/portfolio/etoro_client.py`, `personal/portfolio/etoro_importer.py`, `presentation/dashboard_personal/pages/P2_Portafoglio_eToro.py`.

2. **Migration 007** — completare `shared/db/migrations/duckdb/20260615_007_unified_v2.sql`.
   Tabelle: `vix_signals`, `vix_strategy_outputs`, `futures_ohlcv`, `claims_inflation_signals`,
   `yield_curve_snapshots`, `credit_spread_signals`, `engine_composite_signal`.

3. **Roadmap Unificata 2.0** — procedere nell'ordine delle settimane 1→9.

---

## 11. API E SORGENTI DATI

| Sorgente | Tier | Req/Min | Note |
|---|---|---|---|
| FRED | Free | 120 | Configurata ✅ |
| Yahoo Finance | Free | ~60 | Configurata ✅ |
| Finnhub | Free/Starter | 60–300 | Configurata ✅ |
| Alpha Vantage | Free | 5 | Configurata ✅ — solo fallback |
| SEC EDGAR | Free | 10 | Configurata ✅ |
| eToro API | Ufficiale | TBD | Fix in corso ⚙️ |

**Regola critica:** Ogni chiamata API **deve** passare per `RateLimitManager.acquire(source)`.
I budget sono in `config/rate_limits.yaml`.

---

## 12. DATABASE

### DuckDB (OLAP — dati storici massivi)
- Path: `shared/db/market_data.duckdb` (~1 GB con dati reali utente)
- Accesso: sempre tramite `DuckDBClient.get()` (singleton)
- Migrations: `shared/db/duckdb_migrator.py` → `apply_pending()` all'avvio
- **Mai connettere direttamente senza passare dal client.**
- **Mai modificare lo schema senza uno script SQL di migration.**

### SQLite (OLTP — dati personali/transazionali)
- Path: `shared/db/personal.db`
- Contiene: posizioni eToro, profili investitore, goals, cash flow, alert
- Migrations: Alembic
- Retention dati personali: 10 anni per posizioni, permanente per profili/goals

### Regola di retention (da `config/data_retention.yaml`)
```
DuckDB:  prezzi → 20 anni | macro → 30 anni | sentiment → 3 anni
SQLite:  posizioni → 10 anni | alert_history → 1 anno
```

---

## 13. FEATURE FLAGS

File: `config/feature_flags.yaml`

Prima di implementare funzionalità sperimentali o costose, verificare
se esiste già un flag. Se non esiste, aggiungerlo con default `false`.

```python
from shared.feature_flags import require_enabled, is_enabled

# Guard all'inizio di funzioni costose
require_enabled("pytorch_forecasting")  # lancia FeatureDisabledError se false

# Check condizionale
if is_enabled("realtime_websocket"):
    ...
```

**Flag attuali rilevanti:**
- `edgar_bulk_download: false` — download bulk SEC EDGAR
- `realtime_websocket: true` — WebSocket Finnhub
- `pytorch_forecasting: false` — modelli DL (costosi)
- `advanced_correlation: true` — DCC-GARCH + HMM
- `ollama_narrative: false` — LLM locale (richiede Ollama)

---

## 14. TESTING

### Convenzioni
- Framework: `pytest`
- Property-based: `hypothesis` (per DataCleaner e calcoli finanziari)
- Timing: `freezegun` per test con date
- Coverage minima: **80% globale**, 85% per `engine/alpha_generation/`

### Struttura test
```
tests/
├── shared/           → test infrastruttura (DB, rate limiter, migrator)
├── engine/           → test analisi quantitativa
├── personal/         → test finanza personale
├── bridge/           → test contratti interfaccia
├── integration/      → test pipeline end-to-end su fixture DuckDB
└── fixtures/         → dati di test riutilizzabili
```

### Benchmark di latenza (pytest-benchmark — target da rispettare)

| Test | Target |
|---|---|
| DuckDB query 10 anni prezzi | < 200ms |
| DuckDB write 10k righe | < 500ms |
| DataQualityReport generazione | < 1s |
| VectorBT backtest 10 anni | < 2s |
| Walk-forward 5 split | < 15s |
| Stress test (4 storico + 5 sintetico) | < 30s |
| StrategyComposer.run() | < 500ms |
| CompositeSignalAggregator.compute() | < 200ms |
| MacroConvictionCalculator.compute() 15 serie | < 300ms |
| Monte Carlo 10k simulazioni | < 3s |
| Pagina dashboard più pesante (Q3 correlazioni) | < 3s |

---

## 15. HEALTH & OBSERVABILITY

Il sistema distingue tre stati (Regola 30):

- `OPERATIONAL` — tutte le funzioni disponibili, latenza nei target
- `DEGRADED` — dati parziali, alcune fonti offline, analisi critica ok
- `DOWN` — impossibile operare (DB irraggiungibile, scheduler crashato)

Il `HealthChecker` controlla: DuckDB, SQLite, cache, scheduler.
La `health_status_bar` deve essere visibile in ogni pagina della dashboard.

**Error budget:** se `error_rate` su finestra 5 minuti > 10% → scheduler si
auto-sospende e notifica. Claude Code deve includere
`error_budget.record_error()` in ogni job dello scheduler.

---

## 16. SICUREZZA

- **`.env`** mai in git. Verificare sempre `.gitignore`.
- **API key** mai nel codice, mai nei log, mai nei test.
- **Dashboard Streamlit:** `STREAMLIT_AUTH_ENABLED=true` in produzione.
- **Database:** file `.db` e `.duckdb` mai in git.
- **Dati personali utente:** mai loggare importi, posizioni, profili.
- **Backup:** `BackupManager` configurato, esecuzione giornaliera alle 02:00.

---

## 17. NAVIGAZIONE UI (target post-redesign Settimane 6-7)

```
📡 SISTEMA        → S0 Health & API Status, S1 Analysis Pipeline
🌍 MACRO & CICLO  → M1 Macro Dashboard, M2 Yield Curve, M3 Labour Market, M4 PMI
📊 MERCATI        → K1 Overview, K2 Equity, K3 Bonds, K4 Commodity & Futures, K5 Forex
🔬 ANALISI        → Q1 VIX-Based, Q2 Sentiment, Q3 Correlations, Q4 Forecasting, Q5 Delta
⚙️ STRATEGIE      → T1 Backtesting, T2 Stress Test, T3 Alerts
💰 PERSONAL       → P1–P9 (invariati nel nome)
```

La navigazione attuale (E0–E14) rimane operativa fino al completamento del redesign.
**Non rinominare le pagine esistenti fino alla Settimana 6.**

---

## 18. CHECKLIST PRE-IMPLEMENTAZIONE

Prima di scrivere qualsiasi modulo, verificare:

```
□ Layer corretto? (engine / personal / shared / bridge)
□ Database corretto? (DuckDB OLAP vs SQLite OLTP)
□ Pipeline dati rispettata? (fetch→clean→validate→duckdb→cache→return)
□ DataQualityReport generato?
□ RateLimitManager usato per ogni chiamata API?
□ Feature flag necessario? (default false per funzionalità costose)
□ Backtest con commissioni + slippage + shift(1)?
□ Stress test include scenari forward-looking?
□ Latenza nei target?
□ Import layer-safe? (nessun cross-import diretto engine/personal)
□ Type hints completi su tutte le funzioni?
□ Schema DuckDB modificato → migration SQL creata?
□ Test scritto, coverage ≥ 80%?
□ Health/observability: HealthChecker aggiornato se modulo può fallire silenziosamente?
□ pathlib.Path usato per tutti i percorsi (Windows compatibility)?
```

---

## 19. RISCHI NOTI

| # | Rischio | Probabilità | Impatto | Stato |
|---|---|---|---|---|
| R1 | eToro cambia struttura XLSX | Alta | Medio | `EtoroImporter` facade — aggiornare solo parser |
| R2 | eToro API keys revocate/scadute | Media | Medio | Fallback su XLSX implementato |
| R3 | yfinance blocca futures continui | Media | Alto | FuturesFetcher con ETF proxy come fallback |
| R4 | 28 serie FRED troppo lente | Media | Basso | asyncio batch da 5 + rate limiter |
| R5 | HMM regime non in DB | Alta | Basso | VixSignalCalculator usa `regime=None` come fallback |
| R6 | Migration 007 confligge con tabelle esistenti | Bassa | **Alto** | `IF NOT EXISTS` su ogni CREATE; testare su copia DB |
| R7 | Race condition residue in LiveMarketService | Bassa | Medio | Fix v7.1.1 verificato con 50 thread |

---

## 20. GLOSSARIO RAPIDO

| Termine | Definizione |
|---|---|
| `BaseFetcher` | Classe astratta padre di tutti i fetcher. Implementa la pipeline dati. |
| `DataCleaner` | Applica gap filling, outlier detection, stale detection prima di Pandera. |
| `DataQualityReport` | Score [0,1] della qualità di una serie temporale. Allegato ad ogni dato. |
| `DuckDBMigrator` | Gestisce l'evoluzione schema DuckDB tramite file SQL versionati. |
| `EtoroImporter` | Facade che astrae API ufficiale eToro e fallback XLSX. |
| `EngineCompositeSignal` | Segnale aggregato pesato [-1, 1] da VIX + macro + yield + credit + claims. |
| `FeatureFlag` | Switch booleano YAML che abilita/disabilita funzionalità. Default: false. |
| `InvestorProfile` | Profilo Pydantic che filtra TUTTI i suggerimenti del personal layer. |
| `RateLimitManager` | Controllo centralizzato di tutti i rate limit API. Unico punto di throttling. |
| `WealthSimulator` | Monte Carlo per proiezione patrimonio. 10k simulazioni < 3s. |

---


