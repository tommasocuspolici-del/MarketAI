# MarketAI — Guida per Claude Code

**v12.0.0** · Python ^3.11 · 4728+ test · coverage ≥ 89.1% · ROADMAP v6.0 (32 regole) + Convenzioni 33–40

---

## Architettura a Livelli

```
presentation/       → UI Streamlit  (# pragma: no cover su tutti i file)
bridge/             → Contratti tra engine e personal (api_contracts.py)
engine/             → Calcoli, analytics, dati di mercato
  market_data/      → fetchers, currency_converter, instrument_registry
  alpha_generation/ → segnali macro, VIX, yield curve
    backtest_engine/→ PSR, WFO, FDR, MonteCarlo, CapacityEstimator ★ v12.0
  analytics/        → sentiment, correlation, technical, backtesting
    signals/        → ICCalculator, SignalScorecard, AlphaDecay ★ v12.0
    regime/         → HMMRegimeModel, RegimeTimeline, CUSUM ★ v12.0
    forecasting/    → ConformalPredictor, ModelRegistry, VAR, Ensemble ★ v12.0
    risk/           → CVaRRegime, ComponentVaR, FactorAttribution ★ v12.0
    derivatives/    → SVIModel, VRPCalculator, VolMarkov, GEX ★ v12.0
  risk/ portfolio/  → CVaR, risk contribution, rebalancing
  data_universe/    → UniverseLoader, VintageManager, LagRegistry ★ v12.0
personal/           → Dati utente (portfolio, obiettivi, cashflow, tax)
shared/             → DB, logging, config, resilience, types
  db/               → DuckDBClient (market), SQLiteClient (personal), repos
  resilience/       → error_policy, error_budget, rate_limit_manager
  model_registry/   → ModelRegistryClient (bridge per engine.analytics.forecasting) ★ v12.0
config/             → YAML soli (nessun .py)
  data_universe.yaml→ 88 serie FRED catalogate (Convenzione 38) ★ v12.0
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
OP_CONFIG.cache.signals_disk_ttl_s      # 3600 s  ★ v11.0
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
@st.cache_data(ttl=CACHE_TTL.SIGNALS)           # 3600 s — segnali engine da DuckDB ★ v11.0
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

### Earnings Calendar Fetcher ★ v11.0
```python
from engine.market_data.fetchers.earnings_calendar_fetcher import EarningsCalendarFetcher

db = DuckDBClient(path=...)
fetcher = EarningsCalendarFetcher(client=db)
n = fetcher.fetch_and_persist(["AAPL", "NVDA", "MSFT"])   # yfinance, nessuna API key
df = fetcher.get_upcoming(days=7)       # prossimi 7 giorni → earnings_calendar
df = fetcher.get_historical("AAPL")    # storico 365gg
```
Fonte: `yfinance.Ticker.calendar` + `.earnings_dates`. Migration: `20260521_028_earnings_calendar.sql`.

### Options Flow Fetcher ★ v11.0
```python
from engine.market_data.fetchers.options_flow_fetcher import OptionsFlowFetcher

fetcher = OptionsFlowFetcher(client=db)
n = fetcher.fetch_and_persist(["SPY", "QQQ", "AAPL"])   # yfinance option chain
d = fetcher.get_latest("SPY")          # dict: put_call_ratio, iv_skew_25d, iv_atm
df = fetcher.get_history("SPY", days=30)
```
Calcola: Put/Call ratio su volume (fallback su OI), IV ATM, IV skew 25-delta (±5% da ATM).
Migration: `20260521_029_putcall_ratio.sql` → tabella `putcall_ratio_daily`.

### SignalPersistenceService ★ v11.0
```python
from engine.alpha_generation.signal_persistence_service import SignalPersistenceService
from shared.db.duckdb_client import get_duckdb_client

svc = SignalPersistenceService(duckdb=get_duckdb_client())
result = svc.load_latest(max_age_hours=1)   # None se assente/stale → ricalcolare
if result is None:
    result = CompositeSignalAggregator(duckdb=...).compute()
    svc.persist(result)                     # scrive engine_composite_signal + signal_snapshots
```
Garantisce che il composite signal sopravviva ai riavvii di Streamlit.
Nelle pagine UI usare `CACHE_TTL.SIGNALS` (3600s) su `@st.cache_data`.

### H1 Market Health Matrix ★ v11.0
Pagina `presentation/dashboard_engine/pages_v2/H1_Market_Health_Matrix.py`.
- Griglia 3×3 con 12 indicatori (semafori 🟢/🟡/🔴): Yield Curve, Macro, VIX, Vol Surface, HY OAS, TED, Labour, Sentiment, CAPE, Earnings 7gg, P/C Ratio, IV Skew.
- Health Score 0–100 in cima: `health_score = round((composite_score + 1) / 2 * 100)`.
- Zero API call — solo letture DuckDB (Regola 12).
- Prima voce del gruppo **Mercato** in `sidebar_nav.py`.
- Loader functions testabili senza Streamlit: `load_health_matrix()`, `_load_composite()`, ecc.
- Patch test: `shared.db.duckdb_client.get_duckdb_client` (lazy import dentro la funzione).

### Data Universe ★ v12.0
```python
from engine.data_universe.universe_loader import UniverseLoader, DataUniverse

loader = UniverseLoader()              # carica config/data_universe.yaml (Convenzione 38)
universe = loader.load()
universe.count()                       # 88 serie
universe.by_category("labour")        # list[SeriesDefinition]
universe.get("ICSA")                   # SeriesDefinition | None
```
**Convenzione 38:** `config/data_universe.yaml` è la fonte di verità per tutte le serie.
Non aggiungere serie FRED nel codice Python — aggiungerle nel YAML.

```python
from engine.data_universe.vintage_manager import VintageManager
from engine.data_universe.lag_registry import LagRegistry
from engine.data_universe.audit_logger import AuditLogger

vm = VintageManager(client=db)
vm.record_vintage("ICSA", obs_date, vintage_date, value)   # as-of semantics
df = vm.get_as_of("ICSA", as_of_date)                      # point-in-time lookup

lag_reg = LagRegistry(client=db)
lag_reg.bulk_register_from_universe(universe)              # seed da YAML

audit = AuditLogger(client=db)
audit.log_fetch(source="fred", endpoint="/ICSA", record_count=n, duration_ms=ms)
```

### Signal Quality Framework ★ v12.0
```python
from engine.analytics.signals import ICCalculator, ICResult, SignalScorecard
from engine.analytics.signals import AlphaDecayAnalyzer, StalenessDetector
from engine.analytics.signals import SignalNormalizer, SignalCombiner

# IC rolling Spearman (Convenzione 36 — mai IC statico)
calc = ICCalculator(window=252)
result: ICResult = calc.compute(signal, forward_returns, "vix", horizon_days=21)
# result.ic_mean, ic_tstat, is_significant

# Scorecard persistita in DuckDB signal_scorecard (Convenzione 37)
sc = SignalScorecard(db)
sc.persist_from_ic(result, snapshot_date=date.today(), weight_current=0.16)
df = sc.get_latest()                   # tutti i segnali, riga più recente per ognuno

# Alpha decay half-life
analyzer = AlphaDecayAnalyzer()
decay = analyzer.compute("vix", {21: 0.08, 63: 0.05, 126: 0.03})
# decay.half_life_days, is_decaying

# Normalizzazione
norm = SignalNormalizer()
z = norm.time_series_zscore(signal, window=252)
clipped = norm.clip_outliers(z)        # ±3σ
```

### HMM Macro Regime ★ v12.0
```python
from engine.analytics.regime import HMMRegimeModel, RegimeState, RegimeTimelineRepo
from engine.analytics.regime import RegimeChangeDetector, ConditionalReturnsCalculator

model = HMMRegimeModel()
model.fit(features_df)                 # 12 variabili mensili z-score normalizzate
output = model.predict_current(latest_features)
# output.current_regime: RegimeState (expansion|slowdown|contraction|recovery)
# output.prob_expansion, prob_slowdown, prob_contraction, prob_recovery
# output.confidence = max(prob_i)

repo = RegimeTimelineRepo(db)
repo.persist(output, snapshot_date=date.today())
df = repo.get_history(days=365)        # tabella macro_regime_timeline

detector = RegimeChangeDetector(threshold=5.0)
changes = detector.detect_on_regime_probs(regime_df)  # list[ChangePoint] CUSUM
```
Fallback rule-based se `hmmlearn` non installato (automatico). Feature flag: `hmm_macro_regime_v2`.

### Forecasting Avanzato ★ v12.0
```python
from engine.analytics.forecasting import AdaptiveConformalPredictor, ConformalInterval
from engine.analytics.forecasting import ModelRegistry, ModelEntry
from engine.analytics.forecasting import EnsembleCombiner, ScenarioTreeBuilder

# Conformal Prediction (Convenzione 34 — no ±σ gaussiana)
cp = AdaptiveConformalPredictor(alpha=0.10, calibration_window=252)
cp.update(actual=4.1, forecast=4.0)   # aggiorna calibrazione
interval: ConformalInterval = cp.predict_interval(point_forecast=4.2)
# interval.lower, upper, is_valid (False se < 30 campioni)

# Model Registry (Convenzione 33 — ogni modello registrato con hash dataset)
registry = ModelRegistry(db)
model_id = registry.register_new(
    model_type="xgboost", target_metric="UNRATE", horizon_days=63,
    hyperparams={"n_estimators": 200, "max_depth": 4},
    training_data=df_train,
)
registry.update_metrics(model_id, mse_oos=0.02, mae_oos=0.1, mape_oos=2.5,
                         directional_acc=0.65, is_baseline_beaten=True)

# Scenario tree bear/base/bull
builder = ScenarioTreeBuilder()
tree = builder.build("SPY", base_value=500.0,
                     point_forecast={30: 510.0, 90: 525.0},
                     volatility={30: 0.15, 90: 0.18},
                     current_regime="expansion")
```
Feature flags: `conformal_prediction`, `model_registry`, `var_vecm_engine`, `xgboost_forecaster`, `prophet_forecaster`, `scenario_tree`.
Flag false di default: `lstm_forecaster`, `tft_forecaster`, `nowcasting_midas`.

### Backtesting Professionale ★ v12.0
```python
from engine.alpha_generation.backtest_engine import (
    probabilistic_sharpe_ratio, PSRResult,
    WFORunner, WFOConfig,
    fdr_benjamini_hochberg, FDRResult,
    MonteCarloPathSimulator, MCResult,
    CapacityEstimator,
)

# PSR (Bailey & López de Prado 2012)
result: PSRResult = probabilistic_sharpe_ratio(returns, sr_benchmark=0.0)
# result.psr in [0,1], is_significant = PSR > 0.90

# Walk-Forward Optimization (3Y in-sample, 1Y OOS)
wfo = WFORunner(WFOConfig(in_sample_years=3, oos_years=1, step_months=3))
wfo_result = wfo.run(prices, strategy_fn)
# wfo_result.is_robust = True se tutti i fold PSR > 0.90

# FDR Correction Benjamini-Hochberg
fdr: FDRResult = fdr_benjamini_hochberg(strategy_ids, p_values, alpha=0.05)
# fdr.n_significant, rejected (list[bool])

# Monte Carlo block bootstrap
mc = MonteCarloPathSimulator(n_paths=1000, block_size=21)
mc_result: MCResult = mc.simulate(returns, horizon_days=252)
# mc_result.var_95, cvar_95, p_positive_return

# Capacity
cap = CapacityEstimator(participation_rate=0.05)
result = cap.estimate("SPY", adtv_usd=5e9, daily_turnover=0.02)
```

### Risk & Portfolio Avanzato ★ v12.0
```python
from engine.analytics.risk import (
    CVaRRegimeCalculator, CVaRRegimeResult,
    ComponentVaRCalculator, ComponentVaRResult,
    FactorRiskAttribution, AttributionResult,
    LiquidityAnalyzer,
)

# CVaR condizionale al regime (t-Student MLE per regime)
cvar_calc = CVaRRegimeCalculator()
result: CVaRRegimeResult = cvar_calc.compute(
    returns=portfolio_returns,
    regime_labels=regime_series,
    current_regime_probs={"expansion": 0.6, "slowdown": 0.3, "contraction": 0.1},
)
# result.cvar_blended_95, cvar_by_regime["contraction"].cvar_95

# Component VaR per posizione
comp_calc = ComponentVaRCalculator(confidence=0.95)
contributions: list[ComponentVaRResult] = comp_calc.compute(weights, returns_df, tickers)
# contributions[i].component_var, pct_risk

# Liquidity
liq = LiquidityAnalyzer(participation_rate=0.20)
liq_result = liq.analyze_position("AAPL", position_usd=1e5, volume_series=vol, price_series=px)
# liq_result.days_to_liquidate, is_illiquid
```

### Derivati e Volatilità ★ v12.0
```python
from engine.analytics.derivatives import (
    VRPCalculator, VRPResult,
    VolRegimeMarkov, VolRegime,
    SVIModel, SVIParameters,
    OptionsStrategyScanner,
)

# Volatility Risk Premium
vrp_calc = VRPCalculator()
vrp: VRPResult = vrp_calc.compute("SPY", iv_series, price_series)
# vrp.vrp = iv_atm_30d - rv_30d, vrp.signal in [-1, +1]

# Vol Regime Markov (4 stati: calm/normal/high/extreme)
markov = VolRegimeMarkov()
markov.fit(vix_series)                 # stima matrice transizione storica
state = markov.predict_state(current_vix=18.5)
# state.current_regime, transition_probs, regime_strategy

# SVI Vol Surface fit
svi = SVIModel()
params: SVIParameters = svi.fit(log_moneyness, total_variance, expiry_days=30)
iv_curve = svi.iv_from_svi(params, log_moneyness_grid)

# Strategy scanner
scanner = OptionsStrategyScanner()
recs = scanner.recommend(vol_regime="normal", market_outlook="bullish")
```
Feature flags: `vol_surface_svi`, `vrp_calculator`, `vol_regime_markov`. Default false: `gex_calculator`, `options_strategy_scanner`.

### Nuove Pagine Dashboard ★ v12.0

| Pagina | Tabelle DuckDB | Cache TTL |
|--------|----------------|-----------|
| Q12 Signal Scorecard | `signal_scorecard` | `CACHE_TTL.SIGNALS` |
| Q13 Model Registry | `model_registry`, `wfo_results` | `CACHE_TTL.SIGNALS` |
| Q14 Regime Timeline | `macro_regime_timeline`, `conditional_returns` | `CACHE_TTL.MACRO_CONVICTION` |
| Q15 Risk Attribution | `portfolio_risk_metrics`, `position_risk_contribution` | `CACHE_TTL.PORTFOLIO_TOTALS` |
| Q16 Backtesting Pro | `wfo_results`, `model_registry` | `CACHE_TTL.SIGNALS` |
| Q17 Vol Surface | `vol_surface_snapshots`, `vix_signals`, `putcall_ratio_daily` | `CACHE_TTL.MARKET_KPI` |

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
  engine/
    data_universe/     test_universe_loader, test_vintage_manager, test_audit_logger ★ v12.0
    analytics/
      signals/         test_ic_calculator, test_signal_scorecard, test_alpha_decay ★ v12.0
      regime/          test_hmm_macro_regime ★ v12.0
      forecasting/     test_conformal_predictor, test_model_registry ★ v12.0
      risk/            test_cvar_regime_calculator, test_component_var, test_liquidity ★ v12.0
      derivatives/     test_vrp_calculator, test_vol_regime_markov ★ v12.0
    alpha_generation/
      backtest_engine/ test_psr_calculator, test_fdr_corrector, test_monte_carlo ★ v12.0
    fetchers, cleaning, backtesting, alpha, analytics, risk
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

## Regole Invariabili (ROADMAP v6.0 + Convenzioni 33–40)

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

**Convenzioni aggiunte v12.0 (ROADMAP_MIGLIORAMENTO_v1.0):**

| # | Convenzione |
|---|-------------|
| 33 | `MODEL_REGISTRY` — ogni modello ML registrato in `model_registry` DuckDB con hash dataset e metriche OOS |
| 34 | `CONFORMAL_CI` — intervalli di confidenza via Conformal Prediction adattiva; vietato ±σ gaussiana |
| 35 | `LOOK_AHEAD_DATA` — as-of semantics; `data_vintages` traccia revisioni; nessun dato usato prima della pubblicazione |
| 36 | `IC_DYNAMIC` — IC calcolato rolling 252gg (Spearman) per ogni segnale; nessun IC statico in produzione |
| 37 | `SIGNAL_REGISTRY` — ogni segnale ha una Signal Scorecard persistita in `signal_scorecard` DuckDB |
| 38 | `DATA_UNIVERSE` — `config/data_universe.yaml` è la fonte di verità per tutte le serie dati |
| 39 | `ADAPTIVE_WEIGHTS` — pesi `CompositeSignalAggregator` aggiornati mensilmente via ridge OOS |
| 40 | `FEATURE_PARITY` — nessun modello ML attivo senza battere il baseline (random walk o media storica) |

---

## Convenzione Commit

```
tipo: descrizione breve (≤ 72 char)

Dettaglio opzionale — perché, non cosa.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```
Tipi: `feat` · `fix` · `refactor` · `test` · `docs` · `chore`

---

*v12.0.0 — aggiornato 2026-05-22*
