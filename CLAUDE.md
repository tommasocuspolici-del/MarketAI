# CLAUDE.md — Istruzioni Operative per Claude Code
## MarketAI Professional Edition
### Versione 2.0 — Maggio 2026
### Baseline progetto: v8.0.0 (827 test passing)

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
**Roadmap completata:** ROADMAP_UNIFICATA_v2.md (v2.0, completata al 100%)
**High-Impact Modules:** 2_HIGH_IMPACT_MODULES.md (completati al 100%)

---

## 1. STATO ATTUALE — v8.0.0

| Componente | Stato | Note |
|---|---|---|
| Roadmap Unificata v1.0 (Sett. 0-9) | ✅ COMPLETA | 827 test passing |
| High-Impact Modules (Sett. A-D) | ✅ COMPLETA | VolumeAnalyzer, CVaR, Rebalancing |
| DuckDB migrations | ✅ 001, 007, 008 | 15 nuove tabelle totali |
| Scheduler | ✅ v2.0 | 10 job registrati |
| UI Redesign | ✅ v8.0 | 19 pagine S/M/K/Q/T |
| mypy (nuovi moduli) | ✅ 0 errors | |
| ruff (nuovi moduli) | ✅ 0 warnings | |
| Coverage nuovi moduli | ✅ 94.8% | target ≥ 80% |

---

## 2. AMBIENTE DI SVILUPPO

| Parametro | Valore |
|---|---|
| Sistema operativo | Windows 11 |
| Python | 3.12 |
| Package manager | Poetry |
| Directory progetto | `C:\Q256254\Documenti\marketai\MarketAI1.0` |
| Git | Branch unico: `main` |
| Database DuckDB | ~1 GB, dati reali utente presenti |
| Docker | Non in uso (ambiente locale diretto) |
| Stato attuale | v8.0.0 — Roadmap Unificata + High-Impact COMPLETI |

---

## 3. STRUTTURA DIRECTORY (aggiornata v8.0.0)

```
MarketAI1.0/
├── engine/
│   ├── alpha_generation/          ← NUOVO: MacroConviction, VIX, Composite
│   │   ├── claims_cross_analyzer.py
│   │   ├── composite_signal_aggregator.py
│   │   ├── credit_stress_analyzer.py
│   │   ├── macro_conviction.py
│   │   ├── schemas.py
│   │   ├── strategy_composer.py
│   │   ├── vix_signal_calculator.py
│   │   └── yield_curve_analyzer.py
│   ├── futures_analysis/          ← NUOVO: Roll, Basis, OI, Regime
│   │   ├── basis_analyzer.py
│   │   ├── commodity_regime.py
│   │   ├── open_interest_analyzer.py
│   │   ├── roll_analyzer.py
│   │   └── schemas.py
│   ├── technical/                 ← NUOVO (High-Impact)
│   │   ├── volume_analysis.py     ← OBV, CMF, VWAP, Amihud
│   │   └── divergence_detector.py ← RSI/MACD divergenze
│   ├── risk/                      ← NUOVO (High-Impact)
│   │   ├── cvar_calculator.py     ← CVaR fat-tail t-Student
│   │   └── risk_contribution.py   ← HHI, PRC per asset
│   ├── volatility/                ← NUOVO (High-Impact)
│   │   └── vol_surface.py         ← VIX term structure completa
│   ├── fixed_income/              ← NUOVO (High-Impact)
│   │   └── real_yield_analyzer.py ← Real yield → oro/equity
│   ├── portfolio/                 ← NUOVO (High-Impact)
│   │   └── rebalancing_engine.py  ← HRP, Markowitz, Risk Parity
│   └── market_data/
│       ├── sanity_checker_v2.py   ← NUOVO: VIX, roll, spread
│       └── silent_failure_detector.py ← NUOVO: stale, zero_vol
│
├── bridge/
│   ├── api_contracts.py
│   ├── market_context_builder.py  ← NUOVO: engine → personal
│   └── personal_client.py
│
├── presentation/
│   ├── dashboard_engine/
│   │   ├── app_v8.py              ← NUOVO: navigazione S/M/K/Q/T
│   │   └── pages_v2/              ← NUOVO: 19 pagine v8.0
│   │       ├── S0_Health_API_Status.py
│   │       ├── S1_Analysis_Pipeline.py
│   │       ├── M1_Macro_Dashboard.py
│   │       ├── M2_Yield_Curve.py
│   │       ├── M3_Labour_Market.py     ← ★ NUOVA
│   │       ├── M4_PMI_Leading_Indicators.py ← ★ NUOVA
│   │       ├── K1_Market_Overview.py
│   │       ├── K2_Equity.py
│   │       ├── K3_Bonds_Credit.py
│   │       ├── K4_Commodity_Futures.py ← ★ ESPANSA
│   │       ├── K5_Forex_Options.py
│   │       ├── Q1_VIX_Based_Analysis.py ← ★ NUOVA
│   │       ├── Q2_Sentiment.py
│   │       ├── Q3_Correlations.py
│   │       ├── Q4_Forecasting.py
│   │       ├── Q5_Delta.py
│   │       ├── T1_Backtesting.py
│   │       ├── T2_Stress_Test.py
│   │       └── T3_Alerts.py
│   └── ui/components/
│       ├── regime_composite_badge.py   ← NUOVO
│       ├── yield_curve_chart.py        ← NUOVO
│       ├── claims_cross_panel.py       ← NUOVO
│       ├── futures_term_structure_panel.py ← NUOVO
│       ├── macro_heatmap.py            ← NUOVO (28 FRED)
│       └── engine_signal_summary.py   ← NUOVO
│
├── shared/db/migrations/duckdb/
│   ├── 20260401_001_initial_schema.sql
│   ├── 20260615_007_unified_v2.sql    ← NUOVO: 8 tabelle
│   └── 20260701_008_high_impact_modules.sql ← NUOVO: 7 tabelle
│
├── scripts/run_scheduler.py           ← v2.0: 10 job
├── config/feature_flags.yaml          ← aggiornato: 30+ flag
├── ROADMAP_UNIFICATA_v2.md            ← completata
├── 2_HIGH_IMPACT_MODULES.md           ← completata
└── CLAUDE.md                          ← questo file
```

---

## 4. CONVENZIONI OBBLIGATORIE (32 REGOLE — v6.0)

Invariate dalla v6.0. Testo completo in ROADMAP_v6.md.
Tutte e 32 le regole sono **attive senza eccezioni**.

---

## 5. NUOVI MODULI — INTERFACCE CHIAVE

### CompositeSignalAggregator
```python
from engine.alpha_generation.composite_signal_aggregator import CompositeSignalAggregator
from shared.db.duckdb_client import get_duckdb_client

agg    = CompositeSignalAggregator(duckdb=get_duckdb_client())
output = agg.compute()
# output.composite_score: float [-1, +1]
# output.recommended_action: 'BUY' | 'HOLD' | 'REDUCE'
# output.confidence: 'HIGH' | 'MEDIUM' | 'LOW'
```

### VixSignalCalculator + StrategyComposer
```python
from engine.alpha_generation.vix_signal_calculator import VixSignalCalculator
from engine.alpha_generation.strategy_composer import StrategyComposer

vix_calc  = VixSignalCalculator(prices_repo=get_prices_repository())
composer  = StrategyComposer(vix_calculator=vix_calc, duckdb=get_duckdb_client())
output    = composer.run()
# output.action: 'BUY' | 'HOLD' | 'REDUCE'
# output.position_size_pct: [0, 1]
```

### MacroConvictionCalculator (15 serie FRED)
```python
from engine.alpha_generation.macro_conviction import MacroConvictionCalculator
from shared.db.macro_repo import get_macro_repository

calc   = MacroConvictionCalculator(macro_repo=get_macro_repository())
result = calc.compute()
# result.macro_score: [-1, +1]
# result.confidence: 'HIGH' | 'MEDIUM' | 'LOW'
```

### CommodityRegimeClassifier
```python
from engine.futures_analysis import (
    RollAnalyzer, BasisAnalyzer,
    OpenInterestAnalyzer, CommodityRegimeClassifier,
)

classifier = CommodityRegimeClassifier(
    roll_analyzer=RollAnalyzer(duckdb=db),
    basis_analyzer=BasisAnalyzer(duckdb=db, prices_repo=prepo),
    oi_analyzer=OpenInterestAnalyzer(duckdb=db),
)
analysis = classifier.classify("CL=F")
# analysis.regime: CommodityRegime enum
# analysis.score: [-1, +1]
```

### RebalancingEngine (High-Impact)
```python
from engine.portfolio.rebalancing_engine import RebalancingEngine

engine = RebalancingEngine(
    duckdb=get_duckdb_client(),
    profile_risk="moderate",
    method="hrp",  # 'markowitz'|'hrp'|'risk_parity'|'equal_weight'
    min_trade_eur=50.0,
    drift_threshold=0.05,
)
report = engine.run(
    current_weights={"AAPL": 0.30, "MSFT": 0.25, "SPY": 0.45},
    portfolio_value_eur=50_000.0,
    profile_id="me",
)
```

### MarketContextBuilder (bridge engine→personal)
```python
from bridge.market_context_builder import build_market_context
ctx = build_market_context()
# ctx.equity_expected_return: float
# ctx.equity_volatility: float
# ctx.current_regime: str
# Usato da P7_Scenari_Ricchezza per il Monte Carlo
```

---

## 6. SCHEDULER v2.0 — ORDINE JOB

```
lun-ven ogni 4h:
  :00 → market_prices     (watched_tickers.yaml)
  :05 → futures_prices    (CL=F, GC=F, ES=F + analisi CommodityRegime)
  :15 → yield_curve       (DGS2/10/3M + Estrella-Mishkin)
  :15 → credit_spreads    (HY OAS + TED + NFCI)
  :30 → vix_strategy      (VixSignalCalculator + StrategyComposer)
  :45 → analysis_pipeline (CompositeSignalAggregator → engine_composite_signal)

07:00 lun-ven → macro_fred (28 serie FRED)
16:30 giovedì → claims_cross (Claims/Inflation cross signal)
02:00 daily   → backup
03:00 day 1   → retention
```

---

## 7. UI REDESIGN — NAVIGAZIONE v8.0

```
streamlit run presentation/dashboard_engine/app_v8.py

Gruppi:
  📡 S0 Health & API Status, S1 Analysis Pipeline
  🌍 M1 Macro Dashboard, M2 Yield Curve, M3 Labour★, M4 PMI★
  📊 K1 Market Overview★, K2 Equity, K3 Bonds, K4 Futures★, K5 Forex
  🔬 Q1 VIX-Based★, Q2 Sentiment, Q3 Correlations, Q4 Forecasting, Q5 Delta
  ⚙️ T1 Backtesting, T2 Stress Test, T3 Alerts
  💰 P1-P10 Personal (inclusa P10 Rebalancing★)
```

---

## 8. DATABASE — TABELLE v8.0

### DuckDB (OLAP) — 23 tabelle totali
| Migration | Tabelle |
|---|---|
| 001 initial | prices_ohlcv, macro_series, backtest_results, correlations, ... |
| 007 unified_v2 | vix_signals, vix_strategy_outputs, futures_ohlcv, claims_inflation_signals, yield_curve_snapshots, credit_spread_signals, engine_composite_signal, regime_reports |
| 008 high_impact | volume_signals, divergence_signals, risk_metrics, portfolio_risk_report, vol_surface_snapshots, real_yield_signals, rebalancing_reports |

---

## 9. ANTI-PATTERN VIETATI

Invariati. Vedere ROADMAP_v6.md per la lista completa.

---

## 10. METRICHE CORRENTI (v8.0.0)

| Metrica | Valore |
|---|---|
| Test totali | **827 passing** |
| Coverage nuovi moduli | **94.8%** |
| mypy errors (nuovi moduli) | **0** |
| ruff warnings (nuovi moduli) | **0** |
| Scheduler jobs | **10** |
| DuckDB migrations | **3** |
| Nuove tabelle DuckDB | **15** |
| Pagine UI v8.0 | **19** |

---

## 11. PROSSIME SESSIONI (Opzionali)

Le Settimane 10-11 della Roadmap Unificata sono ancora da implementare
(feature-flagged, disabilitate per default):

- **Settimana 10:** BreadthIndicatorCalculator + COT Parser
  - Flag: `breadth_indicators: false`, `cot_data: false`
- **Settimana 11:** AlphaDecayMonitor + FamaFrenchLoader
  - Flag: `alpha_decay_monitor: false`, `factor_model: false`

---

## 12. PROMPT PER PROSSIMA SESSIONE

```
Continuo lo sviluppo di MarketAI Professional Edition.

Stato attuale: v8.0.0 (827 test passing, mypy 0 errors, ruff 0 warnings).

Roadmap Unificata v1.0: COMPLETATA (Sett. 0-9).
High-Impact Modules: COMPLETATI (Sett. A-D).

Le seguenti funzionalità sono da implementare (opzionali, feature-flagged):
- Settimana 10: BreadthIndicatorCalculator + COT Parser
- Settimana 11: AlphaDecayMonitor + FamaFrenchLoader

[descrivi qui cosa vuoi fare nella prossima sessione]
```
