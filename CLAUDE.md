# MarketAI — Guida per Claude Code

**v10.1.0** · Python ^3.11 · 3080+ test · coverage ≥ 89.1% · ROADMAP v6.0 (32 regole)

---

## Architettura a Livelli

```
presentation/       → UI Streamlit  (# pragma: no cover su tutti i file)
bridge/             → Contratti tra engine e personal (api_contracts.py)
engine/             → Calcoli, analytics, dati di mercato
  market_data/      → fetchers, currency_converter, instrument_registry
  alpha_generation/ → segnali macro, VIX, yield curve
  analytics/        → sentiment, correlation, technical, backtesting
  risk/ portfolio/  → CVaR, risk contribution, rebalancing
personal/           → Dati utente (portfolio, obiettivi, cashflow, tax)
shared/             → DB, logging, config, resilience, types
  db/               → DuckDBClient (market), SQLiteClient (personal), repos
  resilience/       → error_policy, error_budget, rate_limit_manager
config/             → YAML soli (nessun .py)
custom_indicators/  → DSL per segnali custom
tests/              → Mirror della struttura src
```

**Boundary critica:** `personal/` non importa da `engine/analytics`, `engine/risk`,
`engine/alpha_generation`, `engine/portfolio`, `engine/backtesting`.
Usa `bridge/` o `engine/market_data/` direttamente.
Enforced da: `tests/architecture/test_layer_boundaries.py`.

---

## Moduli Chiave — Riferimento Rapido

### Config operativa (zero magic numbers)
```python
from shared.config.operational_config import OP_CONFIG

OP_CONFIG.http.default_timeout_s        # 15.0 s
OP_CONFIG.cache.live_market_ttl_s       # 900 s
OP_CONFIG.fx_fallbacks.gbp_usd          # 1.27
OP_CONFIG.analytics.vix_weight          # 0.60
```
Aggiungi nuovi valori in `config/operational_defaults.yaml`, mai hardcoded in `.py`.

### Tipi core
```python
from shared.types import Currency, Money, TimeFrame, AssetClass, MarketRegime
from shared.signal_types import Signal          # ic_estimate, quality_flag, is_reliable
from shared.exceptions import DataError, DatabaseError, BridgeError  # 25 tipi
```
**Regola 18:** ogni importo monetario porta `Currency` esplicita.
**Regola 19:** tutti i datetime devono essere UTC-aware.

### Conversione prezzi GBX/EUR → USD
```python
from engine.market_data.currency_converter import CurrencyConverter, get_instrument_native_currency

get_instrument_native_currency("SWDA.L")          # "GBX"
CurrencyConverter().ticker_price_to_usd(10426.0, "SWDA.L")  # ~132 USD
```
Suffissi: `.L`→GBX · `.DE/.MI/.PA/.AS/.BR/.LS`→EUR · `.SW`→CHF · `.TO`→CAD · `.AX`→AUD · `.HK`→HKD · `.T`→JPY.
Non duplicare la logica FX; usa sempre `CurrencyConverter`.

### FX Service (runtime rates)
```python
from shared.fx_service import get_fx_service

fx = get_fx_service()
rate = fx.get_rate(Currency.GBP, Currency.USD)   # FxRate con timestamp
```

### Mapping ticker eToro
```python
from engine.market_data.instrument_registry import InstrumentRegistry

reg = InstrumentRegistry()          # nessun get_instance(), costruttore diretto
reg.get_ticker(3040)                # "SWDA.L"
reg.get(3040)                       # InstrumentMapping(display_name, native_currency, ...)
reg.register_from_api(iid, ticker, ...)  # non sovrascrive manual/user_override
```
Fallback seed (5 entry) se DuckDB non disponibile: `_SEED_FALLBACK` in `instrument_registry.py`.
Migration: `shared/db/migrations/duckdb/20260514_017_instrument_registry.sql`

**Regola: nelle pagine presentation** usare `InstrumentRegistry()` per risolvere ticker `#ID`
(es. `#3040` → `SWDA.L`) e passare il ticker reale a `get_live_price_usd()` per la
conversione GBX→USD corretta. I ticker numerici eToro non hanno suffisso `.L`, quindi
`_get_instrument_currency("#3040")` restituisce "USD" (errato) senza questo lookup.

### Database
```python
from shared.db.duckdb_client import DuckDBClient   # market data (singleton)
from shared.db.sqlite_client import SQLiteClient   # personal data (singleton)
from shared.db.prices_repo import PricesRepo
from shared.db.macro_repo import MacroRepo
from shared.db.fundamentals_repo import FundamentalsRepo
```
**Regola 12:** pipeline fetch→DB→read; mai chiamate API nelle funzioni di lettura.
**Regola 9:** tutti i DataFrame validati con Pandera prima della scrittura su DB (`shared/db/schemas.py`).

### Error handling
```python
from shared.resilience.error_policy import apply_error_policy, error_policy, ErrorLevel

@apply_error_policy(level="RECOVER", fallback=None, context="modulo.funzione")
def fetch_price(ticker: str) -> float | None: ...

# oppure inline:
except Exception as exc:
    return error_policy.handle(exc, level=ErrorLevel.DEGRADE, context="ctx", fallback=[])
```
Livelli: `RECOVER` (WARNING + fallback) · `DEGRADE` (ERROR + fallback) · `FATAL` (CRITICAL + rilancia).
Vietato `except Exception: pass` in produzione.

### Logging
```python
from shared.logger import get_logger
log = get_logger(__name__)   # structlog wrapper
```

### Presentation (Streamlit)
```python
from presentation.ui.session_keys import SK
from presentation.ui.cache_policy import CACHE_TTL

st.session_state.get(SK.ETORO_IMPORT_RESULT_API)
st.session_state[SK.FORCE_REFRESH] = True

@st.cache_data(ttl=CACHE_TTL.MARKET_KPI)       # 900 s
@st.cache_data(ttl=CACHE_TTL.MACRO_CONVICTION)  # 3600 s
@st.cache_data(ttl=CACHE_TTL.PORTFOLIO_TOTALS)  # 300 s
```
Non usare stringhe literal per session_state né `ttl=NUM` diretto.

**Pattern refresh manuale (obbligatorio su ogni pagina):**
```python
cols_top = st.columns([4, 1])
with cols_top[1]:
    if st.button("🔄 Aggiorna", key="<page_id>_refresh"):
        st.cache_data.clear()
        st.rerun()
```
Ogni pagina deve esporre il bottone `🔄 Aggiorna` in alto a destra. Per pagine con
azioni aggiuntive (es. caricamento dati da FRED) usare `st.columns([3, 1, 1])` e
aggiungere il bottone secondario prima del refresh.

---

## Pipeline Dati — Trigger Manuali (UI)

Le seguenti pagine espongono bottoni per caricare/aggiornare dati dal DB o da API esterne.
La logica di fetch è sempre **separata** dalla logica di lettura (Regola 12).

| Pagina | Bottone | Cosa fa |
|--------|---------|---------|
| M3 Labour Market | `📥 Carica da FRED` | `ClaimsFetcher + JOLTSFetcher + PayrollFetcher` → `claims_cycle`, `jolts_monthly`, `payroll_sector` |
| M5 Economic Surprise | `📥 Carica consensus` | `ConsensusLoader.load_yaml()` + `.save()` → `economic_consensus` |
| Q9 Labour Forecasting | `🤖 Genera previsioni` | `LabourForecastEngine` (ARIMA+Ridge) su UNRATE/ICSA/JOLTS → `labour_forecasts` |
| Q10 Surprise Heatmap | `📥 Carica consensus` | stesso `ConsensusLoader` di M5 |

**Labour Market fetchers** (in `engine/analytics/labour_market/`):
```python
from engine.analytics.labour_market.claims_fetcher import ClaimsFetcher
from engine.analytics.labour_market.jolts_fetcher import JOLTSFetcher
from engine.analytics.labour_market.payroll_fetcher import PayrollFetcher

fred = FredSimpleClient()       # richiede FRED_API_KEY in .env
db   = DuckDBClient(path=...)
n    = ClaimsFetcher(db, fred).fetch_and_persist(lookback_years=20)
```

**Forecast engine** (orchestrazione in `Q9_Labour_Forecasting._run_forecast_job`):
- Target: `UNRATE` mensile
- Feature: lagged ICSA (1-3M), quits_rate, openings_rate
- Orizzonti: `["1M", "3M", "6M"]`
- Tabella output: `labour_forecasts` (colonne: `generated_at, horizon, target_metric, forecast_value, forecast_lower, forecast_upper, model_used, arima_forecast, ridge_forecast`)

---

## Bug Noti e Fix Applicati

| ID | Pagina | Problema | Fix |
|----|--------|----------|-----|
| B5 | E6 Macro | Serie `"GDP"` restituisce livello in miliardi (~28000), mostrava "31856.26%" | Sostituita con `"A191RL1Q225SBEA"` (Real GDP Growth Rate %, quarterly annualized) |
| B6 | E7 Sentiment | Scores hardcoded (`CNN F&G: 0.45` ecc.) | Aggiunto banner `⚠️ DATI DEMO` |
| B7 | E8 Correlations | Matrice simulata con seed fisso | Aggiunto banner `⚠️ DATI DEMO` + refresh |
| B8 | P2 eToro | Ticker `#3040` mostra `—` come nome | `_extract_display_name` ora usa `InstrumentRegistry` come fallback |
| B9 | P2 eToro | `#3040` prezzo 9782.2 GBX trattato come USD | `_get_current_price_yf` risolve `#ID` → ticker reale → `get_live_price_usd` |

**Attenzione serie FRED GDP**: non usare mai `"GDP"` (livello miliardi) per mostrare la
crescita del PIL in percentuale. Usare `"A191RL1Q225SBEA"` (SAAR trimestrale) o
`"A191RX1Q020SBEA"` (YoY dal precedente anno).

---

## Struttura Test

```
tests/
  architecture/        test_layer_boundaries.py
  engine/              fetchers, cleaning, backtesting, alpha, analytics, risk
  personal/            data_entry, goals, cashflow, networth, tax, wealth_scenarios
  shared/              error_policy, graceful_degradation, mutation_targets, db, fx
  bridge/              test_clients.py
  presentation/        auth, pages, e6_macro
  integration/         richiedono rete / DB reale
  regression/          BUG-004..008 + P1 (< 5s)
  property_based/      Hypothesis
  fixtures/            mock_builders.py
```

**Comandi pytest:**
```bash
pytest                          # tutti (coverage auto)
pytest -m regression            # regressioni storiche, < 5 s
pytest -m slow                  # test lenti
pytest -m integration           # richiedono rete/API
pytest --cov --cov-fail-under=94
```

**Mutation testing** (solo WSL — mutmut non gira nativamente su Windows #397):
```bash
mutmut run --paths-to-mutate engine/market_data/currency_converter.py   # target ≥ 70%
mutmut run --paths-to-mutate personal/data_entry/etoro_aggregator.py    # target ≥ 65%
```

---

## Regole Invariabili (ROADMAP v6.0)

| # | Regola |
|---|--------|
| 1 | Python ≥ 3.11, type hints completi su tutto il codice |
| 3 | Nessuna importazione circolare |
| 7 | Zero magic numbers: usa `OP_CONFIG` o costanti nominate |
| 9 | Tutti i DataFrame validati con Pandera prima della scrittura su DB |
| 12 | Pipeline fetch→DB→read: mai API fetch nelle funzioni di lettura |
| 18 | Ogni importo monetario porta `Currency` esplicita |
| 19 | Tutti i datetime sono UTC-aware |
| 28 | `engine/` non importa da `personal/`; usa `bridge/` |
| 30 | Benchmark engine < 200 ms per operazione |
| 43 | Override manuali rispettati nei KPI di mercato |

---

## Convenzione Commit

```
tipo: descrizione breve (≤ 72 char)

Dettaglio opzionale — perché, non cosa.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```
Tipi: `feat` · `fix` · `refactor` · `test` · `docs` · `chore`

---

*v10.1.0 — aggiornato 2026-05-17*
