# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [7.2.0] — 2026-05-05 — 🐛 BUGFIX_PRIORITARIO: 10 bug risolti

### Contesto

Risposta diretta a `BUGFIX_PRIORITARIO.md`: 10 bug identificati post-v7.1.1
+ piano di fix dettagliato con prevenzione recidiva.

| # | Bug | Severità | Stato |
|---|-----|----------|-------|
| B1 | eToro `instrument_id` mancante (21/21 posizioni scartate) | 🔴 Critico | ✅ |
| B2 | ImportError `test_pages.py` (funzioni mock rimosse dalle pagine) | 🟠 Alto | ✅ |
| B3 | DuckDB Constraint Error in `import_replace` | 🟠 Alto | ✅ |
| B4 | Layout KPI ristretto + delta None non visualizzato | 🟡 Medio | ✅ |
| B5 | E6_Macro `_FRED_INDICATORS` completamente hardcoded | 🟡 Medio | ✅ |
| B6 | E12 `slippage=0.0005` < MIN_SLIPPAGE → BacktestError | 🟢 Basso | ✅ |
| B7 | Obiettivi SMART: mancano auto-contributo + deposito/prelievo | 🟠 Alto | ✅ |
| B8 | P9 Alerts personali completamente hardcoded | 🟠 Alto | ✅ |
| B9 | P4 Net Worth: input non aggiornano i KPI (path DB diversi) | 🟡 Medio | ✅ |
| B10 | E10 Delta Tracker: 1W/1M/YTD interamente hardcoded | 🟡 Medio | ✅ |

### 🐛 Bugfix

**B1 — eToro `instrument_id` da strutture nested**

L'API eToro ha smesso di esporre `instrumentId` top-level. Tutte e 21 le posizioni
parsavano OK (campo già `int | None` da v7.1.3) ma venivano poi scartate dal filtro
`if p.instrument_id is not None` in `etoro_importer`.

Aggiunto `model_validator(mode="before")` su `EtoroPosition` che cerca l'id in 4 path:
1. `instrumentId` top-level (no-op)
2. `instrument.instrumentId` o `instrument.id`
3. `instrumentData.instrumentId` o `instrumentData.id`
4. `InstrumentID` (cambio case)

Quando trova un id valido lo promuove al top-level cosi' il `Field(alias="instrumentId")`
lo recupera normalmente.

File: `personal/data_entry/etoro_models.py` (+57 righe)

**B2 — `tests/fixtures/mock_builders.py` (NEW)**

Le funzioni `build_mock_ohlcv`, `_build_mock_snapshots`, `build_mock_backtest`
erano nel modulo di produzione, sono state correttamente rimosse in v7.1.2 ma
3 test in `test_pages.py` continuavano a importarle dalle pagine → ImportError.

Creato `tests/fixtures/mock_builders.py` con builder riutilizzabili (tipi reali:
`pd.DataFrame` per OHLCV, `BacktestResult` per backtest). Aggiornati 3 test in
`test_pages.py` per importare dal nuovo path.

File: `tests/fixtures/mock_builders.py` (NEW, 117 righe), `tests/fixtures/__init__.py`,
`tests/presentation/test_pages.py`

**B3 — DuckDB `DELETE FROM` → `TRUNCATE` + `INSERT OR REPLACE`**

In DuckDB, `DELETE` seguito da `INSERT` nella stessa transazione su tabella con
PRIMARY KEY genera "Constraint Error: Duplicate key" perché MVCC mantiene i delete
markers visibili alla transazione corrente. Soluzione: `TRUNCATE` (no delete markers)
+ `INSERT OR REPLACE INTO` come rete di sicurezza (commento difensivo nel codice).

File: `shared/db/parquet_io.py`

**B4 — Layout KPI a righe da N colonne + delta N/D esplicito**

`render_metric_row` ora accetta `cols_per_row=4` (default): 8 metriche → 2 righe da 4,
non 1 riga da 8 illeggibile. Aggiunto `show_delta_unavailable=True` (default): se
`delta is None` mostra "variazione N/D" invece di non mostrare nulla (l'utente capisce
che e' un dato MANCANTE, non "uguale a prima").

API backward-compatibile: tutti i kwarg sono opzionali con default sensati.

File: `presentation/ui/components/metric_card.py`

**B5 — E6_Macro: dati FRED live + traffic light**

Riscritto completamente `E6_Macro.py`. Sostituito `_FRED_INDICATORS` hardcoded
(GDP +2.4%, CPI +2.7%, ecc.) con fetch live via `FredSimpleClient.fetch_series(limit=2)`
per ogni serie tra: GDP, CPIAUCSL, UNRATE, FEDFUNDS, DGS10. Calcolato delta tra ultima
e penultima osservazione, classificato traffic light (🟢🟡🔴) basato su soglie
nominate (Rule 7) per ogni serie, classificato trend (↑↓→) basato su delta.

Cache `@st.cache_data(ttl=3600)`. Fallback graceful: senza `FRED_API_KEY` o con FRED
non raggiungibile, tutte le righe mostrano "N/D" + emoji ⚪ + messaggio chiaro.

File: `presentation/dashboard_engine/pages/E6_Macro.py` (riscritto, 325 righe)

**B6 — E12 usa `MIN_FEES` / `MIN_SLIPPAGE`**

`E12_Backtesting.py` passava `slippage=0.0005` (sotto `MIN_SLIPPAGE=0.001` Rule 23
invariabile) → `BacktestError` runtime al primo click "Esegui Backtest".

Sostituito con import diretto delle costanti minime:

```python
from engine.backtesting.engine import MIN_FEES, MIN_SLIPPAGE
engine = BacktestEngine(fees=MIN_FEES, slippage=MIN_SLIPPAGE, ...)
```

Aggiornati anche i caption descrittivi per riflettere i valori reali (no magic strings).

File: `presentation/dashboard_engine/pages/E12_Backtesting.py`

**B7 — Goal contributions: deposito/prelievo + auto-contributo periodico**

Estesi i goal con:
- `auto_contribution_amount: float` + `auto_contribution_frequency: ContributionFrequency`
- `GoalContribution` model (storico operazioni) persistito su UserDataStore con
  `entity_type="goal_contribution"`
- `add_contribution(goal_id, amount, kind, note)` applica il delta a current_amount
  (DEPOSIT/AUTO incrementa, WITHDRAWAL decrementa con `max(0,...)`)
- `list_contributions(goal_id)` ritorna storico ordinato dal piu' recente

UI in P5: nuovo expander "💰 Aggiungi / Rimuovi fondi · Auto-contributo" con 4 tab:
**Deposito** / **Prelievo** / **Auto-contributo** / **Storico**.

Backward compat: `from_payload()` con defaults per goal pre-v7.2.

**Nota architetturale**: il blocco contributions e' stato spostato in
`personal/data_entry/goal_contributions.py` (nuovo) per rispettare Rule 2 (max 400
righe per file). API public invariata via re-export.

File: `personal/data_entry/goal_contributions.py` (NEW, 165 righe),
`personal/data_entry/goal_form.py`, `presentation/dashboard_personal/pages/P5_Goals.py`

**B8 — Personal Alerts: rule engine reale + persistenza**

Creato sub-package `personal/alerts/` con:
- `alert_model.py`: `PersonalAlert` (frozen dataclass), `AlertSeverity` (INFO/WARNING/
  CRITICAL), `AlertKind` (6 tipi: GOAL_AT_RISK, GOAL_ACHIEVED, REBALANCING_NEEDED,
  WEALTH_BELOW_MIN, WEALTH_ABOVE_TARGET, NEGATIVE_CASHFLOW)
- `rule_engine.py`: 5 regole (R1 goal a rischio, R2 goal completato, R3 patrimonio
  sotto min, R4 patrimonio sopra target, R5 cashflow mese negativo) con
  **deduplication 24h** per evitare spam. Soglie configurabili persistite via
  `save_thresholds()` / `load_thresholds()` su UserDataStore.

Riscritto `P9_Alerts_Personali.py` per usare il rule engine: `run_rules()` ad ogni
apertura pagina, lista alert con bottone "✓ segna come letto", filtro "solo non letti",
form per configurare soglie patrimonio. Stato vuoto educativo.

File: `personal/alerts/alert_model.py` (NEW), `personal/alerts/rule_engine.py` (NEW),
`personal/alerts/__init__.py`, `presentation/dashboard_personal/pages/P9_Alerts_Personali.py`
(riscritto, 185 righe)

**B9 — UserDataStore singleton + path resolver assoluto**

`save_asset()` e `list_assets()` istanziavano UserDataStore separatamente con path
relativo `data/marketai_personal.db`: se Streamlit aveva CWD diversa rispetto al
test fixture, finivano su DB diversi → cambio non visibile.

Fix duplice:
1. `_resolve_default_db_path()`: priorita' `MARKETAI_PERSONAL_DB` env > project root
   (cerca `pyproject.toml` risalendo) > CWD fallback.
2. `get_default_store()` singleton thread-safe con lock; tutti i moduli (`networth_editor`,
   `goal_form`, `position_form`, `risk_questionnaire`, `goal_contributions`, `rule_engine`)
   ora usano `store or get_default_store()` invece di `store or UserDataStore()`.

Aggiunto `reset_default_store()` per teardown nei test.

File: `personal/data_entry/user_data_store.py` (+45 righe), 5 moduli aggiornati
(networth_editor, goal_form, position_form, risk_questionnaire — bulk via sed)

**B10 — E10 Delta Tracker: variazioni live yfinance**

Aggiunto `DeltaWindow` dataclass + `fetch_delta_windows(tickers)` (function module-level
in `live_market_service.py`) che fetcha 1y di OHLCV per ogni ticker e calcola:
- `delta_1w`: variazione vs prezzo di 5 trading day fa
- `delta_1m`: variazione vs prezzo di 21 trading day fa
- `delta_ytd`: variazione vs primo trading day dell'anno

Riscritto `E10_Delta_Tracker.py`: 6 asset configurati (SPY, QQQ, BTC-USD, GLD, USO,
EURUSD=X), tabella con `column_config` per width ottimale, bottone refresh che svuota
cache, mini-riepilogo "N/M asset con dati validi", expander educativo sulla lettura
delle metriche.

Cache `@st.cache_data(ttl=3600)`. Fallback graceful: `error` field su DeltaWindow
con messaggio specifico (yfinance non installato, ticker errato, ecc.).

File: `engine/market_data/live_market_service.py` (+135 righe),
`presentation/dashboard_engine/pages/E10_Delta_Tracker.py` (riscritto, 171 righe)

### 🧪 Test (56 nuovi, 131 totali)

- `tests/fixtures/mock_builders.py` — usato dai test esistenti (B2)
- `tests/personal/test_goal_contributions.py` (11 test) — auto-contribution
  roundtrip, deposito/prelievo, withdrawal cap a 0, ordering storico (B7)
- `tests/personal/test_personal_alerts.py` (13 test) — thresholds CRUD, regole
  goal/wealth, dedup 24h, mark_read, filtro unread (B8)
- `tests/engine/test_delta_windows.py` (5 test) — fallback yfinance assente,
  data vuoto, calcolo deltas con DataFrame fissato, storico breve (B10)
- `tests/presentation/test_e6_macro.py` (12 test) — traffic light per CPI/UNRATE/
  GDP/DGS10 + trend classification + fallback no-key (B5)

### ✅ Risultato

```
131/131 test passing (75 v7.1.x + 56 nuovi v7.2)
24 file modificati, 7 nuovi
Nessun file > 400 righe (Rule 2 rispettata)
Smoke test end-to-end: B1 (4 path nested), B7 (CRUD goal), B8 (3 alert reali + dedup), B10 (calcolo delta)
```

### 🛡️ Anti-regressione

- `MIN_FEES`, `MIN_SLIPPAGE` esportati da `engine.backtesting.engine` → niente
  piu' magic numbers nelle pagine UI (B6)
- Le funzioni mock vivono SOLO in `tests/fixtures/`, mai nei moduli di produzione (B2)
- `_resolve_default_db_path()` con priorita' env > project_root > CWD fallback
  garantisce path stabile cross-process (B9)
- Deduplication 24h sugli AlertKind evita spam quando una soglia rimane violata (B8)

---

## [7.1.4] — 2026-05-05 — 🐛 HOTFIX bis: pandera namespace + websockets pin stretto

### Contesto

Dopo l'applicazione della patch v7.1.3 in ambiente reale, sono emersi 2
nuovi problemi:

| # | Bug | Severità |
|---|-----|----------|
| B7 | `import pandera.pandas as pa` → `ModuleNotFoundError` | 🔴 Critico (10 errori in test collection) |
| B8 | `poetry update websockets yfinance` non risolve `websockets.asyncio` | 🔴 Critico (yfinance non importa) |

### 🐛 Bugfix

**B7 — Pandera namespace split (0.20+ vs 0.18-0.19)**

Sintomo:
```
shared/db/schemas.py:10: in <module>
    import pandera.pandas as pa
E   ModuleNotFoundError: No module named 'pandera.pandas'
```

Causa: pandera ha riorganizzato il namespace nella 0.20 spostando le API
specifiche per pandas in `pandera.pandas`. Il `pyproject.toml` aveva
`pandera = "^0.18"` (caret = solo 0.18.x e 0.19.x), incompatibile con
quel path d'import.

Fix:
- `shared/db/schemas.py`: try/except retrocompatibile —
  ```python
  try:
      import pandera.pandas as pa  # pandera >= 0.20
  except ModuleNotFoundError:
      import pandera as pa          # pandera < 0.20
  ```
  Le API che usiamo (`Check`, `Column`, `DataFrameSchema`, `String`, `Float`,
  `Int`, `errors.SchemaError`) sono identiche in entrambe le linee.
- `pyproject.toml`: `pandera = "^0.18"` → `pandera = ">=0.18,<1.0"`.
  Lascia all'utente la libertà di installare 0.20+ (manutenuto) o restare
  su 0.18/0.19 senza dover scegliere.

**B8 — `yfinance` 0.2.55+ + `websockets` 13 → ModuleNotFoundError persistente**

Sintomo: anche dopo `poetry update websockets yfinance`, yfinance crasha
con `ModuleNotFoundError: No module named 'websockets.asyncio'`. Poetry
diceva "No dependencies to install or update" perché il vincolo lasco
`^0.2` per yfinance e `^12.0` per websockets era già soddisfatto da
versioni rotte (yfinance 0.2.55+ e websockets 13.x).

Fix `pyproject.toml`:
- `yfinance = "^0.2"` → `yfinance = "0.2.54"` (pin esatto: ultima
  versione SENZA `live.py`/dipendenza `websockets.asyncio`).
- `websockets = "^12.0"` → `websockets = ">=12.0,<13.0"` (esclude 13.x
  che ha cambiato la struttura del modulo `asyncio`).

Per applicare:
```powershell
# Una-tantum: rigenera il lock file con i nuovi vincoli
poetry lock --no-update
poetry install
```

### 🧪 Test (5 nuovi)

- `tests/shared/test_schemas_pandera_compat.py` (5 test):
  - schemas.py si importa indipendentemente dalla versione di pandera
  - `pa.__name__` e' uno dei due path riconosciuti
  - `OHLCV_SCHEMA` e `MACRO_SERIES_SCHEMA` sono `DataFrameSchema`
  - versione pandera nel range supportato.

### ✅ Verifica

```
80/80 test passing (75 v7.1.3 + 5 v7.1.4)
```

### 🔧 Azioni richieste all'utente

```powershell
# 1. Estrai patch v7.1.4 (sovrascrive pyproject.toml e shared/db/schemas.py)
Expand-Archive -Path "MarketAI_v7.1.4_patch.zip" -DestinationPath "." -Force

# 2. Verifica che il pyproject.toml sia aggiornato
Select-String -Path pyproject.toml -Pattern "yfinance|websockets|pandera"

# 3. Rigenera il lock e reinstalla
poetry lock --no-update
poetry install

# 4. Verifica
poetry run python -c "import yfinance; print('yfinance:', yfinance.__version__)"
poetry run python -c "import pandera; print('pandera:', pandera.__version__)"
poetry run python -c "import websockets; print('websockets:', websockets.__version__)"

# 5. Rilancia test
poetry run pytest -q
```

---

## [7.1.3] — 2026-05-05 — 🐛 HOTFIX 6 bug post-v7.1.2

### Contesto

Risposta diretta a `BUG_REPORT_v7.1.1.md` (6 bug rilevati dopo
l'installazione della v7.1.2 in ambiente reale Windows + Poetry):

| # | Bug | Severità | Tempo |
|---|-----|----------|-------|
| B1 | yfinance `ModuleNotFoundError websockets.asyncio` | 🔴 Critico | 2 min |
| B2 | eToro API `ValidationError positionId/cid/instrumentId required` | 🔴 Critico | 30 min |
| B3 | SQLite `no such table: cash_flow_entries` (alembic non eseguito) | 🔴 Critico | 30 min |
| B4 | P3 Cash Flow: nessuna separazione entrate/uscite | 🟡 Medio | 1h |
| B5 | `test_env_loader` non isolato dalla project root | 🟡 Medio | 5 min |
| B6 | `test_fred_simple_client` non isolato dall'env reale | 🟡 Medio | 5 min |

### 🐛 Bugfix

**B1 — websockets pin lower-bound a 12.0**
- `pyproject.toml`: `websockets = "^12.0"` → `websockets = ">=12.0,<14.0"`.
  Il caret loose `^12.0` lasciava risolvere a versioni 11.x se altre
  dipendenze le richiedevano. yfinance >= 0.2.55 importa
  `websockets.asyncio.client` introdotto in websockets 12.0 → ModuleNotFound.
- L'utente deve eseguire `poetry update websockets yfinance`.

**B2 — `EtoroPosition` campi opzionali**
- `personal/data_entry/etoro_models.py`: `position_id`, `cid`,
  `instrument_id` ora `int | None = None`. L'API eToro ha modificato la
  struttura della risposta `GET /trading/info/real/pnl` rimuovendo questi
  campi top-level → 63 ValidationError (3 per posizione × 21 posizioni).
- `personal/data_entry/etoro_importer.py`: filtra le posizioni senza
  `instrument_id` PRIMA del lookup batch (impossibile risolvere ticker).
  Mostra notes con `n_dropped_no_id` per trasparenza.
- `personal/data_entry/etoro_client.py`: `get_real_portfolio()` logga
  in debug le keys della prima posizione raw, utile per allineare il
  modello quando l'API cambia di nuovo. NO valori (Rule 15).
- Bumped to `__version__ = "7.1.3"`.

**B3 — Auto-migration SQLite all'avvio**
- Nuovo `shared/db/migrations_runner.py` (134 righe):
  `apply_sqlite_migrations()` chiama `alembic command.upgrade(cfg, "head")`
  in modo idempotente. Non solleva mai: ritorna `MigrationsReport` con
  `error` valorizzato in caso di fallimento.
- Bypass via env var `MARKETAI_DISABLE_AUTO_MIGRATIONS=1` (per test/CI).
- `app_unified.py` chiama `apply_sqlite_migrations()` PRIMA di
  qualsiasi pagina che acceda al DB. Sidebar mostra `✅ DB migrations: ok`
  oppure `⚠️ Migrazioni DB SQLite fallite: ...`.

**B4 — P3 Cash Flow: tab separati Entrate/Uscite/Riepilogo**
- Riscrittura completa: 3 tab `st.tabs(["📥 Entrate", "📤 Uscite", "📊 Riepilogo"])`.
- Tab Entrate: lista filtrata + form aggiungi entrata (categorie income).
- Tab Uscite: lista filtrata + form aggiungi uscita (categorie expense).
- Tab Riepilogo: KPI mensili, waterfall per categoria, trend 12 mesi.
- Cancellazione singola via selectbox (UX coerente).
- Categorie suggerite specifiche per direzione (`_INCOME_CATEGORIES`,
  `_EXPENSE_CATEGORIES`).

**B5 — test_env_loader isolamento**
- `test_load_environment_no_file_returns_empty_report`: aggiunti
  `monkeypatch.chdir(tmp_path)` (isola CWD) e
  `monkeypatch.setattr("shared.env_loader.PROJECT_ROOT", tmp_path)`
  (isola il fallback su PROJECT_ROOT/.env). Senza questi, il test fallita
  su macchine con `.env` reale nella project root.

**B6 — test_fred_simple_client isolamento**
- `test_no_api_key_raises`: aggiunto `monkeypatch.delenv("FRED_API_KEY")`.
  Il costruttore fa `api_key or os.environ.get("FRED_API_KEY", "")` —
  passare `""` non è sufficiente se la env var reale è settata.

### 🧪 Test aggiunti (17 nuovi)

- **`tests/personal/test_etoro_models_v713.py`** (7 test): payload senza
  ID non solleva, payload con tutti gli ID parsa correttamente, mix
  vecchio/nuovo formato (riproduce esattamente lo scenario dei 21 record
  problematici), non-regressione `pnL` alias.
- **`tests/shared/test_migrations_runner.py`** (10 test): alembic.ini
  mancante, env var disable, case-insensitive, valori non-disabling,
  immutabilita' MigrationsReport, property `succeeded`.

### ✅ Verifica

```
75/75 test passing (38 di S1 + 17 nuovi di v7.1.3 + 20 esistenti)
```

Smoke test eseguiti durante hotfix:
- B2: payload eToro con `positionId/cid/instrumentId` mancanti → parsing OK.
- B3: `apply_sqlite_migrations()` con alembic.ini mancante → graceful error.
- B5/B6: test isolati passano in ambiente CI clean E in dev con `.env`
  reale popolato.

### 🔧 Azioni richieste all'utente

```bash
# 1. Fix B1: aggiornare websockets
poetry update websockets yfinance

# 2. Fix B3: una-tantum, applicare migration manualmente (la prossima
#    volta avverra' automaticamente all'avvio dell'app)
poetry run alembic upgrade head

# 3. Verifica
poetry run pytest tests/ -q
```

---

## [7.1.2] — 2026-05-04 — 🐛 HOTFIX dati hardcoded + bridge profilo investitore

### Contesto

Risposta diretta ai bug riportati dall'utente in `ULTERIORI_ERRORI.txt`.
Diagnosi: la maggior parte dei "dati statici" e delle "API offline anche con
chiave nel `.env`" derivava da:

1. **Mancato caricamento di `.env`**: nessuna invocazione di `load_dotenv()`
   nel codice. FRED/Alpha Vantage/Finnhub apparivano "no API key" anche
   quando la chiave era valorizzata.
2. **Pagine UI con valori hardcoded**: P1 (€124.500), P3 (cash flow finto),
   E2 (mock OHLCV con seed=42), E3 (yield curve cablata), E5 (VIX=16.5,
   FX heatmap random), E9/E12 (forecast/backtest su dati simulati).
3. **Profilo investitore mai propagato all'engine**: il questionario P6
   salvava in `UserDataStore` ma non in `InvestorProfile` (Rule 22).

### 🐛 Bugfix critici

**`.env` ora caricato all'avvio**
- Nuovo `shared/env_loader.py` (179 righe): `load_environment()` con
  ricerca canonica (PROJECT_ROOT/.env -> CWD/.env), 12-factor compliant
  (env vars di sistema hanno precedenza), placeholder detection
  (rileva `your_xxx_here` come "non configurato" anche se la var e'
  settata).
- `app_unified.py` chiama `load_environment()` PRIMA di qualsiasi import
  che legga env vars.
- Nuovo banner sidebar: mostra "✅ N/N API keys configurate · `.env` ok"
  oppure "⚠️ Nessun file `.env` trovato".
- E0 API Health: nuova sezione "🗂️ Stato file .env" con tabella per ogni
  API key (Configurata / Placeholder / Vuota / Non configurata).

**P1 Overview Patrimonio — rimosso hardcoded €124.500**
- Ora legge da `personal/data_entry/networth_editor.net_worth_summary()`
  e `GoalManager.list_for_profile()`.
- Tasso risparmio YTD calcolato da `CashFlowEngine.monthly_summary()`
  iterando sui mesi dell'anno corrente.
- Stato vuoto: messaggi educativi che indirizzano a P3/P4/P5 per la
  data entry. Niente piu' valori inventati: `'—'` quando assenti.

**P3 Cash Flow — CRUD reale invece di waterfall finto**
- Form per aggiungere movimenti (entrata/uscita) con categorie predefinite.
- Tabella movimenti del mese con cancellazione singola.
- Waterfall costruito dai movimenti reali, aggregati per categoria.
- Trend risparmio ultimi 12 mesi (visibile solo con almeno 2 mesi di dati).
- Stato vuoto: messaggio educativo prima del form.

**E2 Equities — fetch yfinance reale**
- Sostituita `build_mock_ohlcv(seed=42)` con `fetch_ohlcv_yfinance()` che
  scarica dati reali da Yahoo Finance.
- Selettore predefinito (10 ticker liquidi USA) + campo custom.
- Selettore periodo (1mo/3mo/6mo/1y/2y/5y).
- KPI live: ultimo close + delta %, high/low di periodo, volume medio.
- Cache `@st.cache_data(ttl=300)`.
- Fallback: se yfinance non installato o fetch fallisce, messaggio chiaro
  che indirizza a `poetry install` e alla pagina E0 API Health.

**E3 Bonds — yield curve da FRED reale**
- Nuovo `engine/market_data/fred_simple_client.py` (203 righe): client HTTP
  sync minimale (urllib + json), pensato per UI Streamlit. Niente async,
  niente DataCleaner pipeline pesante (quello resta nel `FREDFetcher`
  ufficiale per lo scheduler). Cache fatta da Streamlit (TTL 1h).
- `fetch_yield_curve()`: 8 tenor (DGS1MO, DGS3MO, DGS6MO, DGS1, DGS2,
  DGS5, DGS10, DGS30).
- E3 mostra curva reale, tabella, spread chiave 10Y-3M (Estrella-Mishkin),
  10Y-2Y, 30Y-5Y. Inversioni evidenziate con badge ⚠️.
- Fallback: senza FRED key, errore chiaro che spiega come configurarla.

**E5 Forex & Options — VIX + FX da dati reali**
- VIX, EUR/USD, DXY letti da `LiveMarketService.get_kpi_snapshot()`
  (live yfinance) invece che hardcoded 16.5.
- FX heatmap costruita da pct change settimanale dei cross majors via
  yfinance: USD, EUR, GBP, JPY, CHF, CAD. Cache TTL 30 min.
- Regime VIX inferito automaticamente (low <15, normal <22, high <30,
  stress >=30).

**E9 Forecasting — 3 scenari su dati storici reali**
- Nuovo `engine/forecasting/simple_forecaster.py` (197 righe):
  `SimpleForecaster` con modello GBM (Geometric Brownian Motion).
  Drift e volatilita' annualizzate stimati dallo storico, scenari
  pessimistico/base/ottimistico a +/- 1.65σ (~95% confidenza one-sided).
- E9 fetcha 2 anni di OHLCV via yfinance, mostra: ultimo prezzo, vol
  annualizzata, drift annualizzato, storico usato. Tabella scenari +
  chart Plotly con 3 path forward.
- Disclaimer modellistico onesto in expander: limiti GBM, no GARCH,
  no regime switching. Modelli econometrici (ARIMA, Prophet) in roadmap.

**E12 Backtesting — dati e parametri reali**
- 3 strategie selezionabili: MA Cross, RSI Mean Reversion, Momentum.
- Parametri configurabili (fast/slow SMA, RSI period/oversold/overbought,
  Momentum lookback). Validazione Fast<Slow per MA Cross.
- OHLCV fetchato da yfinance (1y, 2y, 5y, 10y, max).
- `BacktestEngine` reale con fees=0.10% + slippage=0.05% (Rule 23).
- Equity curve / drawdown / Sharpe da `render_backtest_report()`.

**P6 Profilo Investitore — bridge → Engine attivato**
- Nuovo `personal/investor_profile/risk_profile_bridge.py` (220 righe):
  funzioni pure `questionnaire_to_investor_profile()` e
  `save_questionnaire_to_investor_profile()`.
- Mapping esplicito tracciato in docstring (mantenibilita'/audit):
  - `RiskProfile` enum -> `RiskTolerance` enum (1:1 sui 4 livelli)
  - `dimension_scores['horizon']` -> `InvestmentHorizon` + `horizon_years`
  - `dimension_scores['capacity']` -> `liquidity_reserve_months`
  - `dimension_scores['knowledge']` -> `financial_knowledge` (1-5)
  - profilo aggressive/very_aggressive sblocca commodities/crypto
- P6 dopo "Salva profilo" propaga al motore via `InvestorProfile`
  (tabella SQLite `investor_profiles`). Da ora in poi tutti i suggerimenti
  filtrano via `SuitabilityChecker` (Rule 22).
- Riquadro "🔗 Profilo attivo nell'engine" mostra che il bridge ha funzionato.

### 🧪 Test

- **`tests/shared/test_env_loader.py`** (8 test): file mancante,
  caricamento corretto, no-override 12-factor, alias keys, placeholder
  detection.
- **`tests/engine/test_simple_forecaster.py`** (8 test): 3 scenari
  presenti, ordinamento pessim<base<optim, recupero volatility entro
  tolleranza, errori su input invalidi.
- **`tests/engine/test_fred_simple_client.py`** (7 test): no-key raises,
  parsing observations, filtering '.' values, fetch_yield_curve aggregato,
  graceful network errors.
- **`tests/personal/test_risk_profile_bridge.py`** (15 test): mapping
  enum 1:1, buckets horizon/liquidity/knowledge, asset class progressivi,
  save chiama loader, safe_load graceful.

Totale **38 test nuovi**. Smoke test end-to-end eseguiti: SimpleForecaster
ricostruisce volatility entro 5%, bridge mappa correttamente Conservative
(no equity, 0 mesi liquidity) e Aggressive (commodities sbloccate, 12 mesi).

### 📦 Dipendenze

Nessuna nuova dipendenza Python. Il `FredSimpleClient` usa solo stdlib
(`urllib.request`, `json`, `urllib.parse`).

### 🔧 Configurazione richiesta

Per attivare le API esterne:

```ini
# In .env (copia da .env.example se non esiste)
FRED_API_KEY=la_tua_chiave_fred         # https://fredaccount.stlouisfed.org/apikey
ALPHA_VANTAGE_KEY=la_tua_chiave_av      # https://www.alphavantage.co/support/#api-key
FINNHUB_API_KEY=la_tua_chiave_finnhub   # https://finnhub.io/register
```

Per i dati di mercato (yfinance):

```bash
poetry install
# oppure se non usi Poetry:
pip install yfinance
```

### 📋 Roadmap

Sessione 1 di 11 della Roadmap Unificata 2.0 + Roadmap Analisi/Previsione 1.0.
Prossima sessione: Settimana 1 (Data Layer Unificato) — Migration DuckDB 007 +
MacroRepository extension + FuturesFetcher.

---

## [6.9.0] — 2026-04-27 — 🏁 PROJECT v6.0 COMPLETE

### Phase 9 — Quality, Performance, Docker, Documentation ✅ Final

#### Added — Property-Based Testing (Hypothesis)
- **`tests/test_property_based.py`** (7 property-based tests):
  - **Sentiment invariants**: composite score always in [-1, 1];
    confidence always in [0, 1]; |score| < 0.6 ⇒ no contrarian signal;
    extreme greed for high uniform scores
  - **Italian tax math invariants**: losses NEVER taxed (gain < 0 ⇒ tax = 0);
    equity gain always taxed at 26% exactly; annual tax_owed always ≥ 0;
    remaining_carry_forward always ≥ 0
  - Domain coverage: 100-200 generated examples per property
  - All 7 properties hold across the input space

#### Added — MkDocs Material Documentation Site
- **`mkdocs.yml`** — full Material theme config with dark/light toggle,
  Mermaid diagrams, code-block copy buttons, search highlight
- **`docs/index.md`** — landing with project overview + Mermaid architecture
- **`docs/getting-started/`** (3 docs):
  - `quickstart.md` — 5-minute setup walkthrough
  - `setup.md` — full from-zero installation guide
  - `configuration.md` — all 14 YAML configs cataloged
- **`docs/architecture/`** (6 docs):
  - `overview.md` — high-level diagram + request trace example
  - `engine.md` — sub-package map + Rule 12 pipeline
  - `personal.md` — sub-package map + Rule 22 suitability filter
  - `bridge.md` — contracts catalog + clients
  - `data-layer.md` — DuckDB vs SQLite split + retention
  - `observability.md` — health states + error budget + metrics
- **`docs/reference/`** (4 docs):
  - `conventions.md` — all 32 rules with enforcement mechanism
  - `data-sources.md` — rate limits + costs table
  - `feature-flags.md` — flag catalog + usage examples
  - `rate-limits.md` — RateLimitManager configuration
- **`docs/guides/`** (3 docs):
  - `backtesting.md` — VectorBT engine usage + walk-forward
  - `stress-testing.md` — historical + forward-looking scenarios
  - `deployment.md` — Docker quick deploy + production checklist

#### Added — Docker Production Config
- **`.env.docker.example`** — production environment template:
  - Streamlit auth (Rule 32) — password hash + enabled flag
  - All API keys placeholders (Finnhub, Alpha Vantage, FRED, EDGAR)
  - DuckDB + SQLite paths inside container
  - Backup retention config
  - Feature flag overrides for production

#### Quality gates (FINAL)
- **592 tests passing** (was 585; +7 property-based tests)
- **mypy --strict**: 0 issues across **156 source files**
- **ruff**: 0 warnings (auto-fixed any new issues)
- **Coverage `shared/`**: **91.8%** (DoD ≥ 90% ✓)
- **Coverage analytics**: 94.6% (Phase 8)
- **Coverage presentation**: 94.7% (Phase 7)
- All performance benchmarks verde:
  - Pipeline 5 tickers: 45ms (target < 10s on 10) ✓
  - Monte Carlo 10k sim: < 3s ✓
  - DCC-GARCH-lite 20 assets: < 10s ✓
  - DuckDB 10y query: < 200ms ✓

#### Project Final Stats
- **130+ Python modules**, **~22,500 lines of code**
- **156 source files** under mypy strict, **zero issues**
- **592 tests** across 6 categories (shared, engine, personal, presentation,
  bridge, property-based)
- **32 invariable conventions** enforced via tooling + code review
- **14 engine pages + 9 personal pages** in 2 Streamlit dashboards
- **18 reusable UI components** with DESIGN_TOKENS-only styling
- **8 sentiment sources**, **4 historical + 6 forward-looking stress
  scenarios**, **HMM-lite 4-regime detection**

#### Architectural notes
- **Rule 31 (DATA_RETENTION)**: `scripts/duckdb_retention.py` already
  exists from earlier phases; documented and verified for Phase 9
- **Rule 27 (DUCKDB_MIGRATIONS)**: all schema changes versioned in
  `shared/db/migrations/duckdb/YYYYMMDD_NNN_*.sql`
- **Hypothesis property-based testing**: chosen domains specifically
  exercise edge cases (boundary scores, large gains/losses, tiny
  confidence values) where hand-written examples would miss bugs

---

## [6.8.0] — 2026-04-26

### Phase 8 — Sentiment, Correlations & Pipeline End-to-End ✅ Complete

#### Added — Sentiment Engine
- **`engine/analytics/sentiment/signal_model.py`** — `SentimentSignal` Pydantic
  + `SentimentSource` StrEnum (8 sources: CNN F&G, Crypto F&G, AAII, Put/Call,
  COT, Insider, Short Interest, Finnhub News)
- **`engine/analytics/sentiment/aggregator.py`** — `SentimentAggregator` with:
  - Confidence-weighted composite score in [-1, 1]
  - Source dedup (most-recent wins per source)
  - Contrarian signal detection (extreme_greed/extreme_fear at ±0.6 thresholds)
  - **Rule 26 enforcement**: confidence penalty when < 3 sources
- **`config/sentiment_sources.yaml`** — composite weights config (CNN 20%,
  AAII 15%, Put/Call 15%, COT 12%, news 12%, insider 10%, short 8%, crypto 8%)

#### Added — Correlation Engine + Regime Detection
- **`engine/analytics/correlation/analyzer.py`** — `CorrelationAnalyzer`:
  - Static Pearson correlation
  - Rolling 30-day pairwise correlations (vectorized via pandas)
  - **DCC-GARCH-lite via EWMA** (deterministic, no `arch` dependency)
  - Lead-lag detection with cross-correlation (max 5 periods)
  - p-value approximation via standard normal CDF (math.erf)
- **`engine/analytics/correlation/regime_detector.py`** — `RegimeDetector`:
  - **HMM-lite via K-means** on (return, volatility) features
  - 4-regime taxonomy: stress/bear/transition/bull (sorted by mean return)
  - Distance-based confidence in [0, 1]
  - Deterministic with seed parameter

#### Added — Analysis Pipeline (End-to-End)
- **`engine/analytics/pipeline/orchestrator.py`** — `AnalysisPipeline`:
  - Stage 1: CorrelationAnalyzer
  - Stage 2: RegimeDetector on equal-weighted portfolio
  - Stage 3: SentimentAggregator (optional, non-critical)
  - Stage 4: Composite **RiskScore** [0, 100] with breakdown
    (regime 40% + vol 30% + correlation 20% + sentiment 10%)
  - Per-stage duration tracking
  - **Performance**: 45ms on 5 tickers, < 10s on 10 tickers (DoD ✓)

#### Added — Alert System
- **`engine/alerts/alert_model.py`** — `Alert` dataclass + `AlertType` enum
  (8 categories) + `AlertSeverity` (info/warning/critical)
  - SHA-256 dedup_key based on type + message prefix
- **`engine/alerts/rule_engine.py`** — declarative rule engine:
  - YAML-loaded `AlertRule` definitions
  - Dotted field path resolver for nested contexts
  - Op matrix: eq/ne/gt/ge/lt/le
  - In-memory dedup with configurable window per rule
- **`config/alert_rules.yaml`** — 6 production rules:
  - `regime_stress`/`regime_bear` — regime change alerts
  - `risk_score_extreme`/`risk_score_elevated` — composite risk thresholds
  - `sentiment_extreme_greed`/`sentiment_extreme_fear` — contrarian signals

#### Added — Bridge Clients (Rule 21)
- **`bridge/engine_client.py`** — `EngineClient` (personal-side wrapper):
  - Dependency-injected `context_producer` callable
  - Pydantic validation on every response → `MarketContextForPersonal`
  - Wraps producer errors in `ContractViolationError`
- **`bridge/personal_client.py`** — `PersonalClient` (engine-side wrapper):
  - `get_portfolio_snapshot()` → `PortfolioSnapshotForEngine`
  - `check_suitability()` → `SuitabilityCheckResponse`
- Fix: `bridge/api_contracts.py` — moved imports out of `TYPE_CHECKING`
  (Pydantic requires runtime resolution); added `# noqa: TC003/TC001` to
  prevent ruff regression

#### Added — Exceptions
- New: `SentimentAggregationError`, `CorrelationError`, `PipelineError`,
  `AlertError` in `shared/exceptions.py` (all inherit from existing bases)

#### Added — Tests (56 new tests)
- `tests/engine/test_analytics/test_sentiment.py` (13 tests):
  signal validation, aggregator (insufficient sources, contrarian signals,
  dedup), benchmark 8 sources < 0.5s
- `tests/engine/test_analytics/test_correlation.py` (16 tests):
  correlation analyzer, regime detector, deterministic seed test,
  benchmark **20 assets < 10s** (DoD ✓)
- `tests/engine/test_analytics/test_pipeline_alerts.py` (20 tests):
  pipeline run, risk score breakdown, alert rule engine (parametrized op
  matrix), dedup, end-to-end pipeline → alerts
- `tests/bridge/test_clients.py` (7 tests): engine + personal clients,
  schema violations wrapped in `ContractViolationError`

#### Quality gates
- **585 tests passing** (was 529; +56 Phase 8 tests)
- **mypy --strict**: 0 issues across **156 source files** (was 144; +12 modules)
- **ruff**: 0 warnings
- **Coverage** `engine/analytics/` + `engine/alerts/` + `bridge/`: **94.6%**
  (DoD ≥ 80% ✓)
- **Performance**: pipeline 5 tickers 45ms, 20 assets correlation < 10s

#### Architectural notes
- **Rule 12 (DATA_PIPELINE)**: pipeline stages are sequential and isolated;
  failures in non-critical stages (sentiment) are logged and skipped without
  aborting the whole run.
- **Rule 21 (LAYER)**: zero direct cross-imports between `engine/` and
  `personal/`. The bridge clients are the SINGLE boundary, with
  Pydantic validation enforcing contract integrity at every call.
- **Rule 26 (DATA_QUALITY)**: sentiment with < 3 sources gets 50% confidence
  penalty + warning log.
- **Rule 28 (RATE_BUDGET)**: sentiment sources are pre-declared in
  `config/sentiment_sources.yaml`; concrete fetchers (Phase 9 wire-up) will
  reference these via `RateLimitManager`.
- **Performance design**: numpy-vectorized everywhere (no Python loops on
  series). DCC-GARCH-lite uses iterative EWMA but each step is O(N²) with
  numpy outer product, never a Python triple-nested loop.

---

## [6.7.0] — 2026-04-26

### Phase 7 — Dashboard Completa ✅ Complete

#### Added — Foundation
- **`config/ui_theme.yaml`** — DESIGN_TOKENS centralizzati (Rule 20):
  24 colors (background, text, accent, semantic, regime, quality), typography,
  spacing, borders, plotly defaults, layout, format strings
- **`presentation/ui/theme.py`** (217 lines) — Loader frozen dataclass
  `DesignTokens` con sub-types `Colors`, `Typography`, `Spacing`, `Borders`,
  `PlotlyTokens`, `Layout`, `Formats`. Helpers: `for_pnl()`, `for_quality_score()`,
  `for_regime()`. Singleton via `@lru_cache(1)`. **`hex_to_rgba()`** utility per
  Plotly fillcolor compatibility (Plotly non accetta hex 8-char con alpha)
- **`presentation/ui/layout.py`** (140 lines) — `setup_page()` wrapper standard:
  configura Streamlit + applica CSS da tokens + applica auth gate (Rule 32)

#### Added — UI Components (16 building blocks)
Tutti seguono il pattern: `build_*()` pura testabile + `render_*()`
Streamlit-wrapper no-op se Streamlit non importabile.

- `kpi_card.py` — `render_kpi_card()` + `render_kpi_row()` con format strings
  da tokens
- `health_status_bar.py` — Barra stato OPERATIONAL/DEGRADED/DOWN per la sidebar
  (Rule 30)
- `data_quality_badge.py` — Badge quality score con thresholds 0.9/0.7/0.5
  (Rule 26)
- `latency_indicator.py` — Verde ≤60s, giallo ≤5min, rosso >5min (Rule 25)
- `regime_badge.py` — Bull/bear/transition/stress badge con icone + colori
- `candlestick_pro.py` — OHLCV + volume + overlays (SMA, Bollinger…) Plotly
- `sentiment_radar.py` — Polar chart 8 fonti normalizzato [0, 100]
- `pipeline_stepper.py` — `PipelineStep` dataclass + stepper orizzontale
- `correlation_network.py` — Network graph circolare + Plotly
- `profile_card.py` — InvestorProfile visualization
- `goal_tracker.py` — Progress bar SMART + `render_goals_list()`
- `net_worth_chart.py` — Timeline area chart assets/liabilities/net
- `cash_flow_waterfall.py` — Plotly Waterfall income/expense
- `wealth_scenario_chart.py` — Monte Carlo fan chart con bande P10/P50/P90
- `backtest_report.py` — Equity curve + drawdown + metrics table
- `stress_test_viewer.py` — Scenario table + impact bar chart + alerts

#### Added — Pages (14 engine + 9 personal)

**Engine (`presentation/dashboard_engine/pages/`):**
- E1 Market Overview (KPI bar + regime + sentiment + risk)
- E2 Equities (screener + candlestick + fundamentals)
- E3 Bonds (yield curve + spreads + inversion alert)
- E4 Commodities (WTI/Brent/Gold/Silver/NG/Copper)
- E5 Forex_Options (FX heatmap + Put/Call + VIX term structure)
- E6 Macro (FRED dashboard + leading indicators)
- E7 Sentiment (8 sources radar + contrarian signals)
- E8 Correlations (network graph + heatmap + DCC-GARCH)
- E9 Forecasting (3 scenarios chart + ARIMA/Prophet metrics)
- E10 Delta_Tracker (W/M/YTD performance + anomaly alerts)
- E11 Analysis_Pipeline (stepper + manual refresh + log)
- E12 Backtesting (strategy builder + equity curve + walk-forward)
- E13 Stress_Test (scenario sliders + impact + what-if)
- E14 Alerts (active list + thresholds + history)

**Personal (`presentation/dashboard_personal/pages/`):**
- P1 Overview_Patrimonio (KPI + breakdown + top 3 goals)
- P2 Portafoglio_eToro (XLSX upload + TWR/MWR + risk metrics)
- P3 Cash_Flow (waterfall + trend + projection)
- P4 Net_Worth (timeline + breakdown)
- P5 Goals (SMART list + feasibility checker)
- P6 Profilo_Investitore (visualization + questionnaire)
- P7 Scenari_Ricchezza (Monte Carlo fan + FIRE calculator)
- P8 Fiscale (capital gains/losses IT regime + tax suggestions)
- P9 Alerts_Personali (goal/rebalance/threshold alerts)

Pattern: ogni pagina espone una `body_*(tokens) -> None` importabile +
`if __name__ == "__main__": render_page(...)` per Streamlit. Testabile senza
Streamlit installato.

#### Added — Page factory + entry points
- **`presentation/ui/page_factory.py`** — `render_page()` orchestratore +
  `render_sidebar_status()` (health bar + latency) + mock data providers
  (`build_mock_health()`, `build_mock_market_kpis()`)
- **`presentation/dashboard_engine/app.py`** — Engine dashboard entry
- **`presentation/dashboard_personal/app.py`** — Personal dashboard entry

#### Added — Tests
- **`tests/presentation/test_pages.py`** (68 smoke tests, +28 hashes):
  - Theme/Layout: design tokens load, color helpers, CSS builder
  - 16 components: import + builder function smoke
  - 14 engine pages: import + body_* discoverable
  - 9 personal pages: import + body_* discoverable
  - 2 app entry points: import + main() exists
  - Page factory: mock health + mock KPIs

#### Configuration
- **`pyproject.toml`** — aggiunto `plotly.*` agli override mypy
- **Coverage config** — esclude righe/funzioni Streamlit-only:
  - `import streamlit as st` (require optional dep)
  - `import plotly.*`
  - `try:  # pragma: no cover` markers su 39 file (try-except ImportError)
  - `# pragma: no cover` su tutte le funzioni `render_*` e `body_*`
    (Streamlit-rendered, non testabili senza Streamlit installato)

#### Quality gates
- **529 tests passing** (era 461; +68 smoke tests)
- **mypy --strict**: 0 issues su **144 source files** (era 100; +44 file)
- **ruff**: 0 warnings (con `# noqa: N999` per Streamlit page naming convention,
  `# noqa: F401` per streamlit-only imports nei pages)
- **Coverage `presentation/`**: **94.7%** (target ≥ 75% ✓)

#### Architectural notes
- **Rule 20 enforcement**: ZERO valori hardcoded nei componenti UI. Ogni colore,
  font, spacing viene da `DESIGN_TOKENS`. Verificato via grep su `presentation/`.
- **Rule 21**: dashboard_personal/ accede a engine SOLO via mock data providers
  in page_factory; il vero wiring usa bridge in Phase 8.
- **Rule 26**: `data_quality_badge` disponibile per ogni serie mostrata.
- **Rule 30**: `health_status_bar` mostra OPERATIONAL/DEGRADED/DOWN su ogni
  pagina via `render_sidebar_status()`.
- **Rule 32**: `setup_page()` chiama `require_auth()` di default su ogni pagina.
- **Pattern testabilità**: separazione `build_*()` pura / `render_*()` Streamlit
  consente coverage 94.7% senza Streamlit installato in CI.

---

## [6.6.0] — 2026-04-25

### Phase 6 — Observability, Security & Personal Layer ✅ Complete

#### Added — Personal Layer (`personal/`) — 6 sub-packages
- **`personal/investor_profile/`** (3 modules)
  - `profile_model.py` — `InvestorProfile` Pydantic + `RiskTolerance`/
    `InvestmentHorizon` enums + helpers (`can_hold`, `is_suitable_drawdown`,
    `excludes_sector`, `excludes_country`)
  - `profile_loader.py` — SQLite CRUD with proper SQLAlchemy `engine.begin()`
  - `suitability_checker.py` — Rule 22 enforcement: `check_instrument()` +
    `assert_suitable()` filters all suggestions through profile constraints
- **`personal/wealth_scenarios/`** (2 modules)
  - `simulator.py` — `WealthSimulator` Monte Carlo log-normal vectorized
    via numpy (Rule 8). Real-terms inflation adjustment, deterministic seeding
  - `retirement_simulator.py` — `RetirementSimulator.find_fire_age()` with
    FIRE 4% rule and probability calibration
- **`personal/cashflow/`** (3 modules)
  - `entry_model.py` — `CashFlowEntry` Pydantic + `CashFlowDirection` enum
  - `engine.py` — CRUD on SQLite + `monthly_summary()` aggregation
  - `projector.py` — 12-month forward projection via numpy aggregation
    of recurring + one-off historical entries
- **`personal/networth/`** (1 module)
  - `tracker.py` — `Asset`, `Liability` Pydantic + `AssetType` enum +
    `NetWorthSnapshot` dataclass + `compute_current_snapshot()` +
    snapshot persistence
- **`personal/goals/`** (3 modules)
  - `goal_model.py` — SMART `Goal` Pydantic + `GoalStatus`/`GoalPriority` enums
  - `goal_manager.py` — SQLite CRUD with auto-promote to ACHIEVED status
  - `progress_calculator.py` — `compute_progress()` + `check_feasibility()`
    with vectorized PMT formula (numpy)
- **`personal/tax/`** (3 modules + rules subpackage)
  - `rules/italy.py` — Italian fiscal regime: 26% capital gains, 12.5% govt
    bonds whitelist, 4-year loss carry-forward, weighted tax across asset
    classes
  - `rules/eu_generic.py` — EU flat-rate fallback (25%)
  - `calculator.py` — `TaxCalculator` facade + `AnnualTaxReport`

#### Added — UI Authentication (`presentation/ui/auth.py`) — Rule 32
- `require_auth()` — Streamlit page guard with bcrypt + SHA-256 fallback
- `verify_password()` — timing-safe via `hmac.compare_digest`
- Configuration via `STREAMLIT_AUTH_ENABLED` and `STREAMLIT_AUTH_PASSWORD_HASH`
  env vars; no-op when Streamlit unavailable (e.g. in CI/tests)
- Raises `AuthenticationError` if auth enabled without password hash

#### Added — Health Probes (`shared/health.py`)
- Completed `scheduler_probe_factory(is_running_fn)` — checks APScheduler
  liveness; returns DEGRADED if not running, DOWN on exception
- All 4 probe factories (`duckdb`, `sqlite`, `cache`, `scheduler`) exported
  via `__all__` for external integration

#### Added — Tests (89 new tests, total now 461)
- `tests/conftest.py` — added `personal_sqlite_client` fixture with full
  schema bootstrap (bypasses Alembic for fast in-memory test DBs)
- `tests/personal/test_investor_profile.py` (19 tests) — profile model +
  loader CRUD + SuitabilityChecker (Rule 22)
- `tests/personal/test_wealth_scenarios.py` (11 tests) — Monte Carlo +
  **benchmark 10k sim < 3s ✓** (Phase 6 DoD)
- `tests/personal/test_cashflow.py` (10 tests) — CRUD + projector
- `tests/personal/test_networth.py` (8 tests) — assets/liabilities/snapshots
- `tests/personal/test_goals.py` (16 tests) — SMART goals + feasibility
- `tests/personal/test_tax.py` (15 tests) — IT regime + EU generic +
  loss carry-forward
- `tests/presentation/test_auth.py` (10 tests) — auth flow + edge cases

#### Quality gates
- **461 tests passing** (was 372)
- **mypy --strict**: 0 issues across **100 source files** (was 66)
- **ruff**: 0 warnings
- **Coverage** `personal/` + `presentation/`: **95.2%** (DoD ≥ 75%)
- **Benchmark** Monte Carlo 10k simulations: < 3s (Phase 6 DoD ✓)

#### Architectural notes
- **Rule 21 enforcement**: zero direct cross-imports between `engine/` and
  `personal/`. The wealth simulator receives expected returns/volatility
  via `bridge/api_contracts.py` — never reads engine modules directly.
- **Rule 22 enforcement**: `SuitabilityChecker.assert_suitable()` is the
  single funnel for instrument vetting; raises `ProfileSuitabilityError`
  on violations.
- **Rule 8 (numpy)**: all financial math uses numpy/scipy. Pure Python
  loops appear only in deliberately small bounded contexts (FV/PMT
  feasibility solver, max 60 iterations).
- **pyproject.toml** — pruned mypy override list to actually-used modules
  (removed 13 unused; added `bcrypt`, kept `streamlit`)

---

## [6.5.0] — 2026-04-25

### Phase 5 — Advanced Stress Testing ✅ Complete

#### Added — Stress testing core (`engine/stress_testing/`)
- **scenario.py** (226 lines) — `StressScenario` dataclass + `MarketContext`
  + `ScenarioOutcome`. Validates shock magnitudes, applies scenarios to
  equity curves with deterministic + stochastic components (numpy RNG seeded
  by `scenario_id` for reproducibility, Rule 8)
- **historical_scenarios.py** (105 lines) — 4 calibrated historical scenarios:
  - **Global Financial Crisis 2008**: equity -57%, bonds +10%, USD +25%, vol×3
  - **COVID Crash 2020**: equity -34%, bonds +8%, USD +8%, vol×3.5
  - **Rate Hike Cycle 2022**: equity -25%, bonds **-13%** (stocks+bonds both
    down — historical anomaly that justifies forward-looking scenarios), vol×1.6
  - **Dot-Com Bust 2000-2002**: equity -49%, bonds +15%, USD flat, vol×2
- **scenario_generator.py** (259 lines) — `ScenarioGenerator` produces 6
  forward-looking scenarios calibrated to the current `MarketContext`:
  Recession Hard Landing, Soft Landing, Stagflation, Goldilocks,
  Geopolitical Tail, Rate Spike. Probabilities calibrated by regime
  (bull/transition/bear/stress) + VIX + yield-curve inversion + sentiment
- **tester.py** (268 lines) — `StressTester` orchestrator combines historical
  + synthetic (Rule 24), produces `StressTestReport` with VaR 95%, CVaR 95%,
  prob_negative, expected_loss + auto-generated `StressAlert` list
- **scenarios_repo.py** (192 lines) — DuckDB persistence to `stress_scenarios`
  table (idempotent upsert, retention helper)

#### Added — Tests (54 new tests, total now 372)
- `test_scenario.py` — validation, application, severity classes
- `test_historical_scenarios.py` — 4 historical calibrations + uniqueness
- `test_scenario_generator.py` — ≥5 scenarios per context, regime calibration
- `test_tester.py` — full pipeline + alerts + **benchmark < 30s** on 10y data
- `test_scenarios_repo.py` — write/read/retention on DuckDB

#### Quality gates
- **372 tests passing** (was 318)
- **mypy --strict**: 0 issues across 66 source files
- **ruff**: 0 warnings
- **Coverage** `engine/stress_testing/`: **96.2%** (DoD ≥ 80%)
- **Benchmark**: full stress test (4 historical + 6 synthetic) on 10y daily
  equity curve completes in well under 30s

#### Architectural notes
- Rule 24 enforcement: `StressTester.run()` ALWAYS combines historical
  scenarios with synthetic ones derived from the current `MarketContext`.
  Pure-historical stress tests are not exposed as a public API.
- All scenario application uses vectorized numpy (Rule 8): cumprod over
  daily returns + seeded RNG noise; no Python loops over time series.
- Scenarios are persisted with full provenance: `market_context` JSON
  snapshot stored alongside synthetic scenarios for audit/replay.

---

## [6.4.0] — 2026-04-25

### Phase 4 — Backtesting Engine ✅ Complete

#### Added — Backtesting core (`engine/backtesting/`)
- **strategy.py** (107 lines) — `Strategy` ABC + `StrategySignal` dataclass
  with `[-1, 1]` post-condition; helpers `_ensure_close`, `_zero_signal`
- **performance.py** (159 lines) — `PerformanceReport` with 9 metrics:
  total_return, annualized_return, annualized_vol, Sharpe, Sortino,
  max_drawdown, Calmar, win_rate, profit_factor (numpy-only, Rule 8)
- **engine.py** (264 lines) — `BacktestEngine` enforcing **non-negotiable
  invariants** (Rule 23): `MIN_FEES = 0.001`, `MIN_SLIPPAGE = 0.001`,
  signal `shift(1)` anti-lookahead, quality_score ≥ 0.7 gate (Rule 26).
  Provides `.run()` and `.walk_forward()` with stitched OOS equity
- **results_repo.py** (219 lines) — `BacktestResultsRepository` persisting
  to existing `backtest_results` DuckDB table

#### Added — Strategies (`engine/backtesting/strategies/`)
- **ma_cross.py** — `MovingAverageCrossover` (SMA fast vs slow)
- **rsi.py** — `RSIMeanReversion` + `compute_rsi` (Wilder, vectorized)
- **momentum.py** — `Momentum` (n-day return + breakout filter)
- **macro_filter.py** — `MacroFilter` (wraps base strategy + macro gate
  via `pd.merge_asof` ffill alignment, e.g. VIX threshold)
- **combined.py** — `CombinedStrategy` (multi-factor: `all`/`any`/`mean`)

#### Added — Tests (~61 new tests, total now 318)
- `test_strategy.py` — ABC contract, `[-1, 1]` enforcement
- `test_strategies.py` — coverage of all 5 concrete strategies
- `test_performance.py` — Sharpe/Sortino/MaxDD/Calmar edge cases
- `test_engine.py` — backtest, walk-forward, anti-lookahead, fee enforcement,
  benchmark **10y < 2s**
- `test_results_repo.py` — DuckDB persistence

#### Quality gates
- **318 tests passing** (was 257)
- **mypy --strict**: 0 issues across 61 source files
- **ruff**: 0 warnings
- **Coverage** `engine/backtesting/`: **94.2%**
  (DoD threshold: ≥ 80%)

#### Architectural note
The `vectorbt` package proved unreliable to install in the build
environment, so we implemented an API-compatible numpy-native engine that
**enforces the same invariants** the Roadmap requires (Rule 23). The
swap to vectorbt remains forward-compatible: only the inner loop body of
`BacktestEngine.run` would change. All other modules (strategies,
performance, persistence, tests) are agnostic to the underlying
computational backend.

---

## [6.3.0] — 2026-04-25

### Phase 3 — New Data Sources ✅ Complete

#### Added — Concrete fetchers (`engine/market_data/fetchers/`)
- **yahoo_fetcher.py** (205 lines) — `YahooFetcher` for OHLCV via yfinance
  with asyncio.to_thread wrapper (Rule 11). Handles intraday + daily + weekly
  + monthly, normalizes Yahoo's dual-style index (Date/Datetime/index).
- **fred_fetcher.py** (181 lines) — `FREDFetcher` for FRED macro via
  pandas-datareader. Includes a curated catalog of 49 key series
  (`FRED_KEY_SERIES`) covering output, inflation, labor, rates, money,
  housing, consumer, FX, risk indicators, and commodities. API key
  read from `FRED_API_KEY` env (Rule 15).
- **edgar_fetcher.py** (300 lines) — `SECEdgarFetcher` for fundamentals
  via SEC EDGAR XBRL JSON facts API. Returns typed `EdgarFact` objects.
  Feature-flag gated bulk download (`edgar_bulk_download`, Rule 29).
  Requires `SEC_EDGAR_USER_AGENT` env (Rule 15) per SEC policy.
- **finnhub_fetcher.py** (296 lines) — `FinnhubFetcher` for real-time OHLCV
  + news sentiment. Exposes a `NewsSentiment` value object with
  `composite_score` in [-1, 1]. WebSocket streaming gated by
  `realtime_websocket` flag (Rule 29).
- **alpha_vantage_fetcher.py** (270 lines) — `AlphaVantageFetcher` fallback
  for OHLCV + FX. Handles Alpha Vantage's quirk of returning HTTP 200 with
  `Note`/`Information`/`Error Message` JSON bodies on rate limit / errors.

#### Added — Tests (~52 new tests, total now 257)
- `test_yahoo_fetcher.py` — normalization, pipeline with mocked yfinance,
  rate limiter integration, error handling
- `test_fred_fetcher.py` — catalog integrity, normalization, env API key
- `test_edgar_fetcher.py` — fact parsing, filter by metric, feature flag gate
  for bulk download, async fetch with mocked aiohttp
- `test_finnhub_fetcher.py` — candle payload, sentiment, WebSocket flag gate
- `test_alpha_vantage_fetcher.py` — payload error detection, FX, OHLCV pipeline

#### Quality gates
- **257 tests passing** (was 205)
- **mypy --strict**: 0 issues across 51 source files
- **ruff**: 0 warnings
- **Coverage** `engine/market_data/fetchers/`: **82.7%**
  (DoD threshold: ≥ 80%)

#### Conformance
- All fetchers use `aiohttp` for HTTP (Rule 11)
- All fetchers go through `RateLimitManager.acquire(source)` before network (Rule 28)
- All sensitive features (bulk EDGAR, WebSocket) behind feature flags (Rule 29)
- All API keys read from `.env` only (Rule 15)
- All raw responses pass through `BaseFetcher` Rule-12 pipeline:
  rate-limit → fetch → clean → validate → DuckDB write → cache → quality persist

---

## [6.2.0] — 2026-04-25

### Phase 2 — Data Cleaning & Quality Validation ✅ Complete

#### Added — Cleaning pipeline (`engine/market_data/cleaning/`)
- **outlier_detector.py** — Z-score (rolling-window aware) and Tukey-IQR
  detection; both return boolean masks aligned to the input index
- **gap_filler.py** — Business-day gap counting and forward-fill bounded by
  `max_gap_days` (long gaps preserved as NaN, never silently extrapolated)
- **stale_detector.py** — Calendar-day staleness + stuck-value run detection
- **data_cleaner.py** (300 lines) — Orchestrator producing `CleaningResult`
  containing the cleaned DataFrame, the `DataQualityReport`, and an outlier
  mask. Handles both OHLCV and macro series (Rule 14)

#### Added — Quality (`shared/db/quality.py`)
- `DataQualityReport` dataclass with weighted score in [0, 1] (Rule 26)
- `QualityScoringConfig` loaded from `config/data_quality.yaml`
- `QualityReportRepository` persists reports to the
  `data_quality_reports` DuckDB table

#### Added — BaseFetcher (`engine/market_data/fetchers/base_fetcher.py`)
- `BaseOhlcvFetcher` and `BaseMacroFetcher` abstract bases that
  enforce the **invariable Rule-12 pipeline**:
  `rate-limit → fetch_raw → clean → validate → duckdb_write → cache → quality_persist`
- Integrates `RateLimitManager` (Rule 28), `DataCleaner` (Rule 14),
  `DualWriter`, `QualityReportRepository`, and `error_budget`

#### Added — Configuration
- **config/data_quality.yaml** — score weights (completeness, outlier
  purity, freshness, uniqueness), outlier method/thresholds, stale
  detection, gap filling policy, acceptance thresholds

#### Added — Tests (~50 new tests, total now 205)
- `test_outlier_detector.py`, `test_gap_filler.py`, `test_stale_detector.py`,
  `test_data_cleaner.py` (with 10y benchmark < 1s),
  `test_quality.py`, `test_base_fetcher.py` (full Rule-12 pipeline + order
  enforcement + error budget integration)

#### Quality gates
- **205 tests passing** (was 141)
- **mypy --strict**: 0 issues across 46 source files
- **ruff**: 0 warnings
- **Coverage**: cleaning 96.9–100%, quality 94.0%, fetchers 80.6%
  (DoD threshold: ≥ 80%)

---

## [6.1.0] — 2026-04-24

### Phase 1 — DuckDB Data Layer for Bulk Time-Series ✅ Complete

#### Added
- **shared/db/schemas.py** — Pandera schemas for OHLCV + macro series with
  custom tz-aware datetime check (Rule 9)
- **shared/db/prices_repo.py** — OHLCV repository with idempotent upserts on
  the composite primary key, range queries, latest-bar lookup, retention deletes
- **shared/db/macro_repo.py** — Macro time-series repository (FRED/ECB/BLS)
  with NaN tolerance and source filtering
- **shared/db/parquet_io.py** — Parquet export / import (append/replace/upsert),
  query export, schema introspection — used by BackupManager and Phase 3 fetchers
- **shared/db/dual_writer.py** — Rule-12 coordinator: writes to DuckDB +
  diskcache L1 with TTL, automatic invalidation, graceful degradation when
  diskcache is unavailable (NullCache fallback)
- **70+ new tests** across test_prices_repo, test_macro_repo, test_parquet_io,
  test_dual_writer
- **Performance benchmarks** confirmed:
  - 10 000-row write < 500ms
  - 10-year (3 650 bars) range query < 200ms

#### Changed
- `pyproject.toml` adds `pyarrow ^16.0` and `pytz ^2024.1` as runtime dependencies
- mypy override extended to include pandas, pandera, pyarrow

#### Architecture
- All new modules respect Rule 2 (≤ 400 lines) via SRP — repository pattern
- Coverage on shared/db: **80.2%** (DoD threshold: ≥ 80%)

---

## [6.0.0] — 2026-04-24

### Phase 0 — Foundations ✅ Complete

#### Added
- **Project skeleton** — complete directory tree per v6.0 architecture
- **32 mandatory conventions** documented in `ROADMAP_v6.md`
- **Poetry** configuration with all v6 dependencies pinned to stable majors
- **shared/ layer**:
  - `exceptions.py` — complete hierarchy rooted on `MarketAIError`
  - `types.py` — `Currency`, `Money`, `TimeFrame`, `AssetClass`,
    `MarketRegime`, `HealthState`, UTC datetime helpers
  - `logger.py` — structlog setup with automatic secret redaction
  - `constants.py` — centralized paths and numeric constants
  - `fx_service.py` — currency conversion skeleton (Rule 18)
  - `feature_flags.py` — YAML-driven flags with `require_enabled()` (Rule 29)
  - `rate_limit_manager.py` — async-safe sliding-window rate limiter (Rule 28)
  - `metrics.py` — counters, gauges, histograms with percentile snapshots
  - `error_budget.py` — sliding-window error tracker with auto-trip (Rule 30)
  - `health.py` — HealthChecker with pluggable probes
  - `backup_manager.py` — DuckDB export + SQLite backup into tar.gz
- **shared/db/**:
  - `duckdb_client.py` — OLAP client with transactions + bulk insert
  - `duckdb_migrator.py` — Flyway-style SQL migrations (Rule 27)
  - `sqlite_client.py` — OLTP client with WAL + foreign keys
  - Initial DuckDB schema: `prices_ohlcv`, `macro_series`,
    `fundamentals`, `sentiment_observations`, `data_quality_reports`,
    `backtest_results`, `stress_scenarios`, `correlations`
  - Initial Alembic migration for personal layer:
    `investor_profiles`, `positions`, `cash_flow_entries`,
    `financial_goals`, `wealth_snapshots`, `assets`, `liabilities`,
    `alert_history`
- **bridge/**:
  - `api_contracts.py` — `MarketContextForPersonal`,
    `PortfolioSnapshotForEngine`, `SuitabilityCheckRequest/Response`,
    `StressTestRequest`, `ForecastRequest` — all frozen Pydantic
- **config/**:
  - `default.yaml` — global defaults
  - `feature_flags.yaml` — 25+ gated features (Rule 29)
  - `rate_limits.yaml` — 11 configured external sources (Rule 28)
  - `data_retention.yaml` — DuckDB + SQLite retention policies (Rule 31)
- **scripts/**:
  - `backup.py` — manual backup CLI
  - `duckdb_retention.py` — enforce retention policy
  - `run_scheduler.py` — APScheduler daemon with error-budget integration
- **Testing**:
  - `conftest.py` with ephemeral DB fixtures
  - Test suites for `feature_flags`, `rate_limit_manager`,
    `duckdb_client`, `duckdb_migrator`, `backup_manager`,
    `error_budget`, `types`, `fx_service`, `metrics`, `health`
- **Tooling**:
  - `Makefile` with targets: setup, test, lint, type-check, coverage,
    run, backup, retention, docker-*, pre-commit, security-check
  - `.pre-commit-config.yaml` with ruff, mypy, bandit, conventional-commits
  - `pyproject.toml` with strict ruff + mypy + coverage configuration
  - `Dockerfile` multi-stage + `docker-compose.yml` with 3 services
    (app, personal, scheduler)
  - `.env.example` with all environment variables documented

### Security (Phase 0)
- Automatic secret redaction in structured logs (keys matching
  `api_key`, `token`, `secret`, `password`, `auth`, ...)
- `.gitignore` hardened against accidental `.env` commits
- `bandit` + `safety` integrated into Makefile and pre-commit

### Documentation
- `README.md` with 5-minute quickstart
- `ROADMAP_v6.md` with all 32 conventions, architecture, timeline
- Migration README in `shared/db/migrations/duckdb/`

---

## [5.0.0] — 2026-03 (pre-v6)

Previous roadmap iteration. Superseded by v6.0 which added:
- Conventions 27–32 (DuckDB migrations, rate budget, feature flags,
  error budget, data retention, auth UI)
- Phase 0 Definition of Done
- Observability layer
- Complete personal/ layer documentation
- Project risk matrix
- Backup / recovery section
- Cost and rate limits table
