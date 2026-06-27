# 03 — 32 Regole Invariabili e Anti-Pattern

## Regole Obbligatorie v6.0 (32 regole — rispettare SEMPRE)

### ━━ ARCHITETTURA ━━
```
1.  LINGUA          Codice in inglese. Commenti logici in italiano. Docstring in inglese.
2.  SRP             Ogni modulo ha una sola responsabilità. Nessun file supera 400 righe.
3.  TIPI            Type hints Python ovunque. Nessuna funzione senza annotazione completa.
4.  IMPORT          Import assoluti. Nessun import circolare. __init__.py con __all__.
5.  ERRORI          Nessun except generico. Eccezioni custom da shared/exceptions.py.
6.  LOGGING         Solo structlog da shared/logger.py. Mai print() in produzione.
7.  COSTANTI        In shared/constants.py o OP_CONFIG da YAML. Zero magic numbers.
8.  MATEMATICA      Sempre numpy/scipy. Mai float nativo per finanza.
9.  DATI            Ogni DataFrame ha schema Pandera esplicito. Zero dtype "object".
10. TEST            Ogni funzione pubblica ha almeno un test unitario. Coverage ≥ 80%.
```

### ━━ DATI E PERSISTENZA ━━
```
11. ASYNC           Chiamate rete sempre async/await (aiohttp). Mai requests in produzione.
12. DATA_PIPELINE   Ogni fetch segue: fetch → clean → validate → duckdb_write → cache → return
                    Ordine INVARIABILE. Nessuna eccezione.
13. DUCKDB          Dati storici massivi (prezzi, macro, fondamentali): DuckDB obbligatorio.
                    SQLite solo per dati relazionali/transazionali (profili, posizioni, goals).
14. CLEAN_FIRST     Ogni dato grezzo passa per DataCleaner prima della validazione Pandera.
15. SICUREZZA       Nessuna API key nel codice. .env + python-dotenv. Zero secret nei log.
16. VERSIONE        Ogni modulo espone __version__ = "X.Y.Z".
17. COMMIT          Conventional Commits: feat:, fix:, refactor:, docs:, test:, perf:, chore:
```

### ━━ LAYER E COMUNICAZIONE ━━
```
18. VALUTE          Ogni importo ha Currency esplicita. Conversione via shared/fx_service.py.
19. DATE            Nessuna data naive. UTC internamente, locale in UI.
20. UI              Zero valori hardcoded nei componenti. Tutti da OP_CONFIG/DESIGN_TOKENS.
21. LAYER           engine/ ↔ personal/ SOLO tramite bridge/api_contracts.py.
22. PROFILO         Ogni suggerimento filtrato da InvestorProfile. Zero eccezioni.
```

### ━━ QUALITÀ ANALITICA ━━
```
23. BACKTEST        Usare VectorBT o RealisticBacktester.
                    Nessun backtest senza: commissioni ≥ 0.001, slippage ≥ 0.001, shift(1).
24. STRESS_TEST     Include: (a) scenari storici, (b) scenari sintetici forward-looking.
25. LATENCY         Dati real-time: aggiornamento ≤ 60 secondi. WebSocket dove disponibile.
26. DATA_QUALITY    Ogni serie ha DataQualityReport. quality_score < 0.5 → warning, skip.
```

### ━━ NUOVE v6.0 ━━
```
27. DUCKDB_MIGRATIONS  Schema DuckDB: SOLO via script SQL in shared/db/migrations/duckdb/
                       YYYYMMDD_NNN_descrizione.sql. Mai modificare schema manualmente.
28. RATE_BUDGET        Ogni fetcher usa RateLimitManager.acquire(source). Nessun bypass.
29. FEATURE_FLAGS      Feature sperimentali/costose → config/feature_flags.yaml (default: false)
30. ERROR_BUDGET       SLA: latenza P95 ≤ 2s; uptime scheduler ≥ 99%.
                       Se error_rate 5min > 10% → scheduler auto-sospende.
31. DATA_RETENTION     DuckDB: prezzi → 20 anni; macro → 30 anni; sentiment → 3 anni.
                       SQLite: posizioni storiche → 10 anni; alert_history → 1 anno.
32. AUTH_UI            Dashboard protetta da password. Mai deployare esposta senza auth.
```

---

## Anti-Pattern Vietati (lista completa)

### ━━ ARCHITETTURA ━━
```
❌ engine/ importa da personal/                → solo via bridge/
❌ personal/ importa da engine/                → solo via bridge/ (o engine/market_data)
❌ management_ui.py importa shared.*           → SOLO stdlib + pystray + Pillow
❌ File > 400 righe                            → refactoring in sottomoduli
❌ Ticker senza suffisso borsa                 → market_registry/resolver.py sempre
❌ Importi senza Currency                      → Currency enum sempre
❌ Feature sperimentale abilitata di default   → feature_flags.yaml obbligatorio
❌ print() in qualsiasi modulo non-test        → get_logger(__name__) sempre
❌ except Exception: pass                      → error_policy sempre
❌ Any implicito nei type hints                → tipizzare esplicitamente
```

### ━━ DATI ━━
```
❌ Fetch API senza clean+validate              → DataCleaner PRIMA di Pandera
❌ Dati grezzi direttamente in DB              → fetch→clean→validate→duckdb→cache→return
❌ Dati senza DataQualityReport               → quality_score sempre calcolato
❌ Dati con quality < 0.5 in calcoli critici  → warning + skip o approvazione esplicita
❌ Loop Python su serie storiche               → numpy/VectorBT vettorizzato
❌ datetime naive                              → pd.Timestamp con tz="UTC"
❌ float per calcoli finanziari               → np.float64 o Decimal
❌ API key hardcoded                           → .env obbligatorio
❌ Fetch senza RateLimitManager               → shared/resilience/rate_limit_manager.py
❌ Schema DuckDB modificato manualmente       → migration SQL sempre
❌ "GDP" per crescita percentuale             → usare "A191RL1Q225SBEA"
```

### ━━ BACKTESTING ━━
```
❌ Backtest senza commissioni                  → fees ≥ 0.001 SEMPRE
❌ Backtest senza slippage                     → slippage ≥ 0.001 SEMPRE
❌ Look-ahead bias                             → shift(1) su TUTTI i segnali
❌ Confronto modelli in-sample                 → walk-forward o purged k-fold
❌ Stress test solo storico                    → aggiungere scenari sintetici forward-looking
```

### ━━ QUALITÀ ━━
```
❌ LLM per calcoli quantitativi               → LLM solo per narrativa/commento
❌ DataFrame senza schema Pandera             → schema sempre
❌ RiskScore senza breakdown                  → componenti sempre esposti
❌ Sentiment da < 3 fonti                     → minimo 3 fonti indipendenti
❌ Correlazione senza regime                  → DCC-GARCH o rolling + HMM label
❌ Suggerimento senza profilo                 → InvestorProfile sempre
❌ Previsione senza 3 scenari                 → pessimistico/base/ottimistico
❌ Colori hardcoded in UI                     → OP_CONFIG/DESIGN_TOKENS sempre
```

### ━━ OPERATIVITÀ ━━
```
❌ Dashboard esposta senza auth               → STREAMLIT_AUTH_ENABLED=true
❌ Backup DuckDB non configurato              → BackupManager obbligatorio
❌ Error rate > 10% ignorato                  → scheduler auto-sospensione
❌ Dati oltre retention policy                → duckdb_retention.py mensile
❌ personal/ usata senza InvestorProfile      → profilo caricato prima di qualsiasi suggerimento
```

### ━━ PYTORCH/ML ━━
```
❌ PyTorch con CUDA/ROCm su Windows           → CPU only (ROCm instabile su RX 6700)
❌ torch.compile() su Windows/CPU             → non supportato, mai usarlo
❌ N-BEATS training senza check RAM           → ram_check.require_ram(4.0, ...) obbligatorio
❌ XGBoost con tree_method="gpu_hist"         → usare tree_method="hist" (CPU)
❌ Modello DL abilitato di default            → feature_flags.yaml: nbeats_model: false
❌ Batch size > 64 per LSTM/N-BEATS           → max 32-64 su 16GB RAM
```

---

## Checklist Pre-Implementazione per Ogni Modulo

```
□ 1.  Layer corretto? (engine/personal/shared/bridge/presentation)
□ 2.  Database corretto? (DuckDB OLAP vs SQLite OLTP)
□ 3.  Pipeline dati rispettata? (fetch→clean→validate→duckdb→cache→return)
□ 4.  DataQualityReport allegato?
□ 5.  RateLimitManager usato per API esterne?
□ 6.  Feature flag necessario? (feature sperimentale o costosa)
□ 7.  Backtest con fees ≥ 0.001, slippage ≥ 0.001, shift(1)?
□ 8.  Stress test include scenari sintetici forward-looking?
□ 9.  Layer-safe imports? (engine/* non importa personal/* e viceversa)
□ 10. Type hints completi? (nessun Any implicito)
□ 11. Schema DuckDB modificato? → migration SQL OBBLIGATORIA
□ 12. Test scritto e pytest -m regression: 0 failed?
□ 13. Health/observability? (se modulo può fallire silenziosamente)
□ 14. CPU-only per PyTorch? (nessun CUDA/ROCm)
```

---

## Riferimenti vault correlati

- [[Backtesting Strategies]] — esempi pratici di applicazione delle regole 23 (fees/slippage)
- [[Risk Scoring]] — applicazione pratica regola anti-pattern "RiskScore senza breakdown"
- [[Sentiment Engine]] — applicazione regola "Sentiment da < 3 fonti"
- [[08_bugfix_protocol]] — routing degli anti-pattern verso i fix
