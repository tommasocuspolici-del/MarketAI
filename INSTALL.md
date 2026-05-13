# MarketAI — MEGA PATCH v9.0 · Roadmap v3.0 Completa
## Patch finale che include tutti i file delle Settimane 1-10

---

## RIEPILOGO SETTIMANE IMPLEMENTATE

| Settimana | Blocco | Contenuto | Status |
|---|---|---|---|
| **Sett 1** | A — Fondamentali | EDGAR XBRL parser + AV Fundamentals + FundamentalsRepo | ✅ |
| **Sett 2** | A — Data Quality | WebSocket Finnhub + DataQualityAlerter + CrossSourceValidator | ✅ |
| **Sett 3/4** | B — Pattern | PatternDetector 8 pattern + PatternSignalsRepo + overlay UI | ✅ |
| **Sett 5** | B — DSL | DSLEvaluator (sandbox-safe) + IndicatorRegistry + K2 tab | ✅ |
| **Sett 6** | C — Surprise v2 | ConsensusLoader + SurpriseAggregatorV2 + AccuracyTracker | ✅ |
| **Sett 7** | Infra | Scheduler refactoring (830→180 righe) + CompositeSignalV3 | ✅ |
| **Sett 8** | UI | CompositeGauge + K1_Markets dashboard | ✅ |
| **Sett 9** | E — Backtest | DSLStrategy + BacktestRunner + ForwardScenarioGenerator | ✅ |
| **Sett 10** | Final | T1_Backtesting + T2_Stress_Test + QA Check | ✅ |

---

## STRUTTURA ZIP (56 file)

```
mega_patch/
├── config/
│   ├── feature_flags.yaml          ← SOSTITUIRE
│   ├── watched_tickers.yaml        ← SOSTITUIRE
│   ├── pattern_config.yaml         ← NUOVO
│   └── surprise_engine_consensus.yaml  ← NUOVO (aggiornare con consensi reali)
│
├── shared/
│   ├── exceptions.py               ← SOSTITUIRE (aggiunge DSLParseError, DSLEvalError)
│   ├── db/
│   │   ├── fundamentals_repo.py    ← NUOVO
│   │   └── migrations/duckdb/
│   │       ├── 20260901_011_fundamentals_edgar.sql
│   │       ├── 20260901_012_data_quality_alerts.sql
│   │       ├── 20260901_013_pattern_signals.sql
│   │       ├── 20260901_014_user_indicators.sql
│   │       ├── 20260901_015_consensus_estimates.sql
│   │       └── 20260901_016_backtest_results.sql
│
├── engine/
│   ├── market_data/
│   │   ├── live_market_service.py  ← SOSTITUIRE (aggiunge WS integration)
│   │   ├── websocket_manager.py    ← NUOVO
│   │   ├── fetchers/
│   │   │   ├── edgar_fundamentals_parser.py  ← NUOVO
│   │   │   └── alpha_vantage_fundamentals_fetcher.py  ← NUOVO
│   │   └── hardening/
│   │       ├── data_quality_alerter.py  ← NUOVO
│   │       └── cross_source_validator.py  ← NUOVO
│   ├── technical/
│   │   ├── pivot_utils.py          ← NUOVO
│   │   ├── pattern_schemas.py      ← NUOVO
│   │   ├── pattern_recognition.py  ← NUOVO
│   │   ├── pattern_signals_repo.py ← NUOVO
│   │   ├── indicator_dsl.py        ← NUOVO
│   │   └── indicator_registry.py   ← NUOVO
│   ├── analytics/
│   │   ├── composite_signal_v3.py  ← NUOVO
│   │   └── surprise_engine/
│   │       ├── consensus_loader.py      ← NUOVO
│   │       └── surprise_aggregator_v2.py  ← NUOVO
│   ├── backtesting/
│   │   ├── strategy_builder.py     ← NUOVO
│   │   └── backtest_runner.py      ← NUOVO
│   └── stress_test/
│       ├── __init__.py             ← NUOVO (vuoto)
│       └── forward_scenarios.py    ← NUOVO
│
├── presentation/
│   ├── dashboard_engine/pages_v2/
│   │   ├── K1_Markets.py           ← NUOVO
│   │   ├── K2_Equity.py            ← SOSTITUIRE (aggiunge tab Indicatori)
│   │   ├── T1_Backtesting.py       ← SOSTITUIRE
│   │   └── T2_Stress_Test.py       ← SOSTITUIRE
│   └── ui/components/
│       ├── pattern_overlay.py      ← NUOVO
│       └── composite_gauge.py      ← NUOVO
│
├── scripts/
│   ├── scheduler_utils.py          ← NUOVO
│   ├── scheduler_jobs_data.py      ← NUOVO
│   ├── scheduler_jobs_analysis.py  ← NUOVO
│   ├── run_scheduler.py            ← SOSTITUIRE (180 righe, era 830)
│   └── qa_check.py                 ← NUOVO
│
└── tests/  (14 nuovi file di test)
```

---

## PASSI DI INSTALLAZIONE (ordine critico)

### Passo 1 — Backup
```powershell
# Prima di tutto, fai un backup del progetto attuale
Compress-Archive -Path "MarketAI" -DestinationPath "MarketAI_backup_pre_v9.zip"
```

### Passo 2 — Estrai e copia i file
```powershell
# Estrai lo ZIP
Expand-Archive -Path "MarketAI_mega_patch_v9.zip" -DestinationPath "mega_patch_temp" -Force

# Copia mantenendo la struttura (Windows)
robocopy mega_patch_temp\mega_patch MarketAI /E /IS /IT

# Oppure su macOS/Linux:
cp -R mega_patch_temp/mega_patch/* MarketAI/
```

### Passo 3 — Crea file `__init__.py` vuoti mancanti
```powershell
New-Item -Path "MarketAI\engine\stress_test\__init__.py" -ItemType File -Force
New-Item -Path "MarketAI\tests\engine\test_technical\__init__.py" -ItemType File -Force
New-Item -Path "MarketAI\tests\engine\test_analytics\__init__.py" -ItemType File -Force
New-Item -Path "MarketAI\tests\engine\test_backtesting\__init__.py" -ItemType File -Force
```

### Passo 4 — Configura variabili d'ambiente (.env)
```env
# Aggiungi al tuo .env (se non già presenti)
SEC_EDGAR_USER_AGENT=TuoNome tua@email.com
ALPHA_VANTAGE_KEY=la_tua_chiave_av_premium
FINNHUB_API_KEY=la_tua_chiave_finnhub
```

### Passo 5 — Applica le migrations DuckDB (6 nuove)
```powershell
poetry run python -c "
from shared.db.duckdb_migrator import run_pending_migrations
run_pending_migrations()
print('Migrations applicate!')
"
```

### Passo 6 — Esegui i test di verifica
```powershell
# Test rapido (solo file nuovi v9.0)
poetry run pytest tests/engine/test_backtesting/ tests/engine/test_technical/ tests/engine/test_analytics/ tests/presentation/ -v

# Test completo (226+ test)
poetry run pytest tests/ -q --tb=short
```

### Passo 7 — QA Check
```powershell
poetry run python scripts/qa_check.py
# Atteso: ✅ QA PASS — 0 violazioni
```

### Passo 8 — Aggiorna consensus manuale
```powershell
# Apri config/surprise_engine_consensus.yaml
# Aggiorna le date e i valori consensus per le prossime release macro
notepad config\surprise_engine_consensus.yaml
```

### Passo 9 — Avvia l'app
```powershell
poetry run streamlit run app_unified.py
```

---

## NUOVE FUNZIONALITÀ DOPO L'INSTALLAZIONE

### Fundamentals EDGAR + Alpha Vantage (K2 → tab 📋)
- Leggi bilanci da SEC EDGAR XBRL automaticamente
- P/E, EV/EBITDA, dividend yield da Alpha Vantage

### Pattern Recognition (K2 → tab 📈, K1 → tab ⚡)
- H&S, Double Top/Bottom, Triangoli, Cup&Handle, Flag
- Badge Plotly sovrapposti al candlestick

### Indicatori DSL Personalizzati (K2 → tab 🔧, K1 → tab 🔧)
- Crea indicatori con: `EMA(close, 20)`, `RSI(close, 14) > 70`
- Preview live prima del salvataggio

### Composite Signal v3 (K1 → tab 🎯)
- Gauge circolare Plotly con breakdown 8 componenti
- Peso pattern tecnici (5%) aggiunto

### Backtesting DSL (T1)
- Backtest qualsiasi espressione DSL su ticker reali
- Walk-forward validation integrata

### Stress Test Forward-Looking (T2)
- 5 scenari sintetici: Recession, Inflation, Credit Crisis, Goldilocks, Base
- Equity curve comparativa per scenario

---

## NOTE IMPORTANTI

⚠️ **Settimana 4 (etichettatura)**: la Pattern Recognition (Roadmap Sett 4) è stata
implementata nella Chat Sett 3. Il contenuto è completo, solo l'etichetta era sfasata.

⚠️ **Debito tecnico pre-v9.0** (7 warning QA, non violazioni):
- `live_market_service.py` — 829 righe (da refactoring futuro)
- `P2_Portafoglio_eToro.py` — 635 righe
- `rebalancing_engine.py` — 468 righe
- `surprise_engine.py` — 463 righe
- `sanity_checker.py` — 449 righe
- `macro_repo.py` — 424 righe
- `20260901_012_fundamentals_scores.sql` — duplicato numerazione (rimuovere)

⚠️ **Roadmap non completata** (fuori scope sessioni):
- Sett 6 Roadmap: Breadth Indicators + COT Parser
- Sett 7-13 Roadmap: ML avanzato + Portfolio Intelligence
