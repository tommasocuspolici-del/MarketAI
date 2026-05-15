# MarketAI — Guida per Claude Code

Versione corrente: **v8.1.0** (ROADMAP_CODE_QUALITY_v1.0 completata).
Baseline: 827 test originali → 1545+ test totali, coverage ≥ 94.8%.
Convenzioni attive: 32 regole ROADMAP v6.0.

---

## Architettura a Livelli

```
presentation/   → UI Streamlit (# pragma: no cover)
bridge/         → Contratti tra engine e personal
engine/         → Calcoli, analytics, dati di mercato
personal/       → Dati personali utente (portafoglio, obiettivi)
shared/         → Utilities trasversali (DB, logging, config)
config/         → File YAML di configurazione (non .py)
tests/          → Test (mirror della struttura src)
```

**Layer boundary**: `personal/` non importa direttamente da `engine/analytics`,
`engine/risk`, `engine/alpha_generation`, `engine/portfolio`, `engine/backtesting`.
Usa `bridge/` o `engine/market_data/` direttamente.
Test automatico: `tests/architecture/test_layer_boundaries.py`.

---

## Riferimenti Rapidi — Moduli Chiave v8.1.0

### Costanti operative (magic numbers)
**File:** `config/operational_defaults.yaml` + `shared/config/operational_config.py`

```python
from shared.config.operational_config import OP_CONFIG

timeout = OP_CONFIG.http.default_timeout_s        # 15.0 s
ttl     = OP_CONFIG.cache.live_market_ttl_s       # 900 s
gbp_usd = OP_CONFIG.fx_fallbacks.gbp_usd          # 1.27
```

Non aggiungere mai numeri hardcoded nei `.py` per valori operativi.
Aggiungerli al YAML e leggere via `OP_CONFIG`.

### Conversione prezzi GBX/EUR → USD
**File:** `engine/market_data/currency_converter.py`

```python
from engine.market_data.currency_converter import (
    CurrencyConverter, get_instrument_native_currency,
)

ccy  = get_instrument_native_currency("SWDA.L")    # "GBX"
conv = CurrencyConverter()
usd  = conv.to_usd(10426.0, "GBX")                # ~132 USD
usd  = conv.ticker_price_to_usd(10426.0, "SWDA.L") # stesso risultato
```

**Regola:** tutti i moduli che gestiscono prezzi di mercato devono usare
`CurrencyConverter`. Non duplicare la logica GBX/EUR/USD.

Suffissi noti: `.L` → GBX, `.DE/.MI/.PA/.AS/.BR/.LS` → EUR,
`.SW` → CHF, `.TO` → CAD, `.AX` → AUD, `.HK` → HKD, `.T` → JPY.

### Mapping ticker eToro
**File:** `engine/market_data/instrument_registry.py`

```python
from engine.market_data.instrument_registry import InstrumentRegistry

registry = InstrumentRegistry()
ticker   = registry.get_ticker(3040)    # "SWDA.L"
mapping  = registry.get(3040)           # InstrumentMapping(...)
```

**Per aggiungere nuovi mapping:** UI P2 → tab Import → sezione "🗂️ Gestione
ticker #ID". Oppure `registry.register_from_api(iid, ticker, ...)` per mapping
automatici (non sovrascrivono quelli `manual` o `user_override`).

**Fallback:** se DuckDB non disponibile, `get()` usa `_SEED_FALLBACK` (5 mapping
storici: #3040 SWDA.L, #3434 CSPX.L, #15435 EIMI.L, #3394 EUN5.DE, #10569 IBCN.DE).

Migration: `shared/db/migrations/duckdb/20260514_017_instrument_registry.sql`

### Error handling
**File:** `shared/resilience/error_policy.py`

```python
from shared.resilience.error_policy import apply_error_policy, error_policy, ErrorLevel

# Decorator (funzione intera)
@apply_error_policy(level="RECOVER", fallback=None, context="my_module.my_fn")
def fetch_price(ticker: str) -> float | None:
    ...

# Inline nel blocco except
try:
    ...
except Exception as exc:
    return error_policy.handle(exc, level=ErrorLevel.DEGRADE, context="ctx", fallback=[])
```

Livelli: **RECOVER** (log WARNING + fallback), **DEGRADE** (log ERROR + fallback),
**FATAL** (log CRITICAL + rilancia).

**Regola:** nessun `except Exception: pass` nel codice di produzione.
Ogni eccezione deve essere loggata almeno a WARNING.

### Session state Streamlit
**File:** `presentation/ui/session_keys.py`

```python
from presentation.ui.session_keys import SK

result = st.session_state.get(SK.ETORO_IMPORT_RESULT_API)
st.session_state[SK.FORCE_REFRESH] = True
```

Non usare stringhe literal per chiavi `session_state`. Aggiungere nuove chiavi
alla classe `_SessionKeys` in `session_keys.py`.

### Cache TTL Streamlit
**File:** `presentation/ui/cache_policy.py`

```python
from presentation.ui.cache_policy import CACHE_TTL

@st.cache_data(ttl=CACHE_TTL.MARKET_KPI)       # 900s
@st.cache_data(ttl=CACHE_TTL.MACRO_CONVICTION)  # 3600s
@st.cache_data(ttl=CACHE_TTL.PORTFOLIO_TOTALS)  # 300s
```

Non usare `ttl=NUM` direttamente nelle pagine.

---

## Struttura Test

```
tests/
  architecture/   → test_layer_boundaries.py (confini architetturali)
  engine/         → test unit per engine/
  personal/       → test unit per personal/
  regression/     → test di non-regressione BUG-004..008 + P1
  shared/         → test unit per shared/
    test_error_policy.py        — ErrorPolicy (16 test)
    test_graceful_degradation.py — stati degradati (32 test)
    test_mutation_targets.py    — test anti-mutanti currency_converter + aggregator
  integration/    → test con DB reale / rete
```

**Marker pytest:**
- `pytest -m regression` — solo i test di regressione bug storici (< 5s)
- `pytest -m slow` — test lenti
- `pytest -m integration` — richiedono rete/API

### Mutation testing
Mutmut non gira nativamente su Windows (issue #397). Usare WSL.
```bash
# In WSL:
mutmut run --paths-to-mutate engine/market_data/currency_converter.py
mutmut run --paths-to-mutate personal/data_entry/etoro_aggregator.py
```
Target: `currency_converter.py` ≥ 70%, `etoro_aggregator.py` ≥ 65%.

---

## Regole Invariabili (estratto ROADMAP v6.0)

- **Regola 1:** Python ≥ 3.12, type hints completi.
- **Regola 3:** Nessuna importazione circolare.
- **Regola 7:** Costanti con nome, zero magic numbers nel codice.
- **Regola 12:** Pipeline fetch→DB→read: mai fetch API nelle funzioni di lettura.
- **Regola 28:** I moduli engine non importano da personal (solo via bridge).
- **Regola 30:** Benchmark engine < 200ms per operazione.
- **Regola 43:** Override manuali rispettati nei KPI di mercato.

---

## Convenzione Commit

```
git commit -m "tipo: descrizione breve (≤ 72 char)

Dettaglio opzionale. Perché, non cosa.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

Tipi: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`.

---

*Aggiornato per v8.1.0 — ROADMAP_CODE_QUALITY_v1.0 completata (2026-05-15)*
