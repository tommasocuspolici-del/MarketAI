# 02 — Architettura Layer, Moduli Chiave e Pattern

## Struttura Directory

```
market_ai/
├── app_unified.py               ← entry point Streamlit
├── launcher.py                  ← avvia MarketAI.exe
├── management_ui.py             ← Management UI (ZERO import interni)
├── presentation/
│   ├── ui/
│   │   ├── auth.py              ← require_auth() — chiamare su ogni pagina
│   │   ├── theme.py
│   │   ├── session_keys.py      ← SK constants per st.session_state
│   │   └── cache_policy.py      ← CACHE_TTL constants
│   ├── dashboard_engine/pages/  ← E*, K*, M*, N*, Q*, S*, A*, C* pages
│   └── dashboard_personal/pages/ ← P* pages
├── bridge/
│   └── api_contracts.py         ← contratti Pydantic engine ↔ personal
├── engine/
│   ├── market_data/
│   │   ├── providers/           ← DataProvider ABC, ProviderRegistry (v12)
│   │   ├── currency_converter.py ← CurrencyConverter, ticker_price_to_usd()
│   │   ├── instrument_registry.py ← InstrumentRegistry (NO get_instance!)
│   │   └── fetchers/            ← fetcher legacy (non usare direttamente)
│   ├── alpha_generation/        ← segnali macro, VIX, yield curve, composite
│   ├── analytics/
│   │   ├── forecasting/         ← base_model.py, ensemble, nbeats, features
│   │   ├── sentiment/           ← v2, 8 fonti aggregate
│   │   ├── correlation/         ← DCC-GARCH, regime-conditional
│   │   ├── backtesting/         ← realistic_backtester.py (v14)
│   │   └── evaluation/          ← advanced_metrics, drift_detector (v14/15)
│   ├── risk/                    ← CVaR, risk contribution, rebalancing
│   └── portfolio/
├── personal/
│   ├── investor_profile/        ← InvestorProfile, suitability_checker
│   ├── portfolio/               ← etoro_importer, performance_calculator
│   ├── cashflow/                ← engine, projector, budget_tracker
│   ├── networth/                ← tracker, asset/liability models
│   ├── goals/                   ← goal_manager, feasibility_checker
│   ├── wealth_scenarios/        ← WealthSimulator Monte Carlo
│   ├── tax/                     ← calculator Italia 26% capital gain
│   └── user_preferences/        ← session_repo, preferences_loader (v15)
├── shared/
│   ├── types.py                 ← Currency, Money, TimeFrame, AssetClass, MarketRegime
│   ├── exceptions.py            ← 25+ custom exceptions
│   ├── logger.py                ← get_logger() — structlog wrapper
│   ├── constants.py
│   ├── fx_service.py            ← get_fx_service().get_rate()
│   ├── signal_bus.py            ← SignalBus.get_instance()
│   ├── signal_types.py          ← Signal dataclass
│   ├── feature_flags.py         ← is_enabled(), require_enabled()
│   ├── health.py                ← HealthChecker, SystemStatus
│   ├── config/
│   │   ├── operational_config.py ← OP_CONFIG (da YAML, mai magic numbers)
│   │   └── cache_ttl_config.py  ← CACHE_TTL constants
│   ├── resilience/
│   │   ├── error_policy.py      ← apply_error_policy, error_policy, ErrorLevel
│   │   ├── error_budget.py
│   │   └── rate_limit_manager.py ← acquire(source) — unico punto throttling
│   └── db/
│       ├── duckdb_client.py     ← DuckDBClient.get() singleton
│       ├── duckdb_migrator.py   ← apply_pending() all'avvio
│       ├── sqlite_client.py     ← SQLiteClient singleton
│       ├── dual_writer.py
│       ├── prices_repo.py
│       ├── macro_repo.py
│       ├── fundamentals_repo.py
│       └── migrations/
│           ├── duckdb/          ← YYYYMMDD_NNN_descrizione.sql
│           └── sqlite/          ← gestite da Alembic
├── config/                      ← YAML only (mai .py in config/)
│   ├── operational_defaults.yaml
│   ├── feature_flags.yaml       ← default false per feature costose
│   ├── rate_limits.yaml
│   ├── data_sources.yaml
│   └── backtesting.yaml
└── tests/
    ├── architecture/
    │   └── test_layer_boundaries.py ← enforces boundary critica
    ├── engine/
    ├── personal/
    ├── shared/
    ├── bridge/
    ├── integration/             ← @pytest.mark.integration (richiede rete)
    ├── regression/              ← @pytest.mark.regression (< 5s, sempre 0 failed)
    └── property_based/          ← Hypothesis
```

## Pattern Presentation (obbligatori su ogni pagina)

```python
from presentation.ui.auth import require_auth
from presentation.ui.session_keys import SK
from presentation.ui.cache_policy import CACHE_TTL
import streamlit as st

require_auth()  # SEMPRE prima riga di ogni pagina

# Cache TTL corretti:
@st.cache_data(ttl=CACHE_TTL.MARKET_KPI)        # 900 s  — prezzi live
@st.cache_data(ttl=CACHE_TTL.MACRO_CONVICTION)   # 3600 s — macro, fondamentali
@st.cache_data(ttl=CACHE_TTL.PORTFOLIO_TOTALS)   # 300 s  — portfolio utente

# Refresh manuale (obbligatorio su ogni pagina, in alto a destra):
cols_top = st.columns([4, 1])
with cols_top[1]:
    if st.button("🔄 Aggiorna", key="<page_id>_refresh"):
        st.cache_data.clear()
        st.rerun()
```

## Conversione Prezzi GBX/EUR → USD

```python
from engine.market_data.currency_converter import CurrencyConverter, get_instrument_native_currency

get_instrument_native_currency("SWDA.L")                    # → "GBX"
CurrencyConverter().ticker_price_to_usd(10426.0, "SWDA.L") # → ~132 USD
```

Suffissi borsa: `.L`→GBX · `.DE/.MI/.PA/.AS/.BR/.LS`→EUR · `.SW`→CHF · `.TO`→CAD · `.AX`→AUD · `.HK`→HKD · `.T`→JPY

**Mai duplicare logica FX.** Usare sempre CurrencyConverter.

## Instrument Registry

```python
from engine.market_data.instrument_registry import InstrumentRegistry
reg = InstrumentRegistry()          # costruttore diretto, NO get_instance()
reg.get_ticker(3040)                # → "SWDA.L"
reg.get(3040)                       # → InstrumentMapping completo
```

**Nelle pagine presentation:** risolvere `#3040` → `SWDA.L` prima di passare a `get_live_price_usd()`.

## FX Service (runtime)

```python
from shared.fx_service import get_fx_service
rate = get_fx_service().get_rate(Currency.GBP, Currency.USD)  # FxRate con timestamp
```

## Error Handling

```python
from shared.resilience.error_policy import apply_error_policy, error_policy, ErrorLevel

@apply_error_policy(level="RECOVER", fallback=None, context="modulo.funzione")
def fetch_price(ticker: str) -> float | None: ...

# Inline:
except Exception as exc:
    return error_policy.handle(exc, level=ErrorLevel.DEGRADE, context="ctx", fallback=[])
```

Livelli: `RECOVER` (WARNING+fallback) · `DEGRADE` (ERROR+fallback) · `FATAL` (CRITICAL+rilancia)

**MAI:** `except Exception: pass` in produzione.

## Signal Bus (comunicazione inter-modulo)

```python
from shared.signal_bus import SignalBus
bus = SignalBus.get_instance()
bus.publish("regime_changed", payload={"regime": "bear"})
bus.subscribe("regime_changed", handler_fn)
```

Non sostituire con eventi Streamlit per logica di business.

## Operational Config

```python
from shared.config.operational_config import OP_CONFIG
OP_CONFIG.http.default_timeout_s        # 15.0
OP_CONFIG.cache.live_market_ttl_s       # 900
OP_CONFIG.fx_fallbacks.gbp_usd          # 1.27
OP_CONFIG.analytics.vix_weight          # 0.60
```

**Mai hardcodare** questi valori. Sempre da OP_CONFIG o da config/ YAML.

## Pipeline Trigger Manuali (pagine specifiche)

| Pagina | Bottone | Azione |
|---|---|---|
| M3 Labour Market | `📥 Carica da FRED` | `ClaimsFetcher + JOLTSFetcher + PayrollFetcher → DB` |
| M5 Economic Surprise | `📥 Carica consensus` | `ConsensusLoader.load_yaml().save()` |
| Q9 Labour Forecasting | `🤖 Genera previsioni` | `LabourForecastEngine (ARIMA+Ridge)` |

## Bug Noti e Fix Applicati

| ID | Modulo | Problema | Fix |
|---|---|---|---|
| B5 | E6 Macro | `"GDP"` → `"31856.26%"` | Usa `"A191RL1Q225SBEA"` (Real GDP Growth Rate %) |
| B6 | E7 Sentiment | Scores hardcoded | Banner `⚠️ DATI DEMO` |
| B7 | E8 Correlations | Matrice simulata seed fisso | Banner `⚠️ DATI DEMO` + refresh |
| B8 | P2 eToro | `#3040` mostra `—` | `_extract_display_name` usa `InstrumentRegistry` fallback |
| B9 | P2 eToro | `#3040` prezzo GBX trattato come USD | `get_live_price_usd` via ticker reale risolto |

**Regola GDP:** Mai usare `"GDP"` (livello miliardi) per crescita percentuale. Usare sempre `"A191RL1Q225SBEA"`.

---

## Riferimenti vault correlati

- [[Architecture Overview]] — panoramica visuale con diagrammi
- [[Market Analysis Engine]] — dettaglio engine/analytics/ e engine/alpha_generation/
- [[Forecasting Engine Map]] — relazioni tra moduli di previsione
- [[Engine Overview]] — panoramica engine layer
- [[Personal Overview]] — panoramica personal layer
- [[Bridge Overview]] — contratti API cross-layer
