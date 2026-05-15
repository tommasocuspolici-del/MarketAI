# CLAUDE TEMA — Convenzioni Obbligatorie (Progetto MarketAI)

> **Assoluto:** Incollare all’inizio di ogni sessione AI.  
> Nessuna modifica alle regole qui sotto senza riunione di architettura.

## 🔒 ARCHITETTURA
1. **LINGUA** → Codice inglese, commenti logici in italiano, docstring inglese.
2. **SRP** → Ogni modulo una responsabilità. Max 400 righe per file.
3. **TIPI** → Type hints Python ovunque. Zero funzioni senza annotazione.
4. **IMPORT** → Assoluti. Vietati circolari. `__init__.py` con `__all__`.
5. **ERRORI** → No `except:`. Eccezioni custom da `shared/exceptions.py`.
6. **LOGGING** → Solo `structlog` da `shared/logger.py`. Mai `print()` in produzione.
7. **COSTANTI** → In `shared/constants.py` o YAML. Zero magic number.
8. **MATEMATICA** → Sempre `numpy`/`scipy`. Mai `float` nativo per finanza.
9. **DATI** → Ogni DataFrame ha schema `pandera` esplicito. Zero dtype `object`.
10. **TEST** → Ogni funzione pubblica ha almeno un test unitario. Coverage ≥ 80%.

## 📀 DATI E PERSISTENZA
11. **ASYNC** → Chiamate rete sempre `async/await` (`aiohttp`). Mai `requests`.
12. **DATA_PIPELINE** → `fetch → clean → validate → duckdb_write → cache → return`. Ordine invariabile.
13. **DUCKDB** → Dati massivi (prezzi, macro, fondamentali). SQLite solo per dati relazionali/transazionali.
14. **CLEAN_FIRST** → Ogni dato grezzo passa per `DataCleaner` prima di `pandera`.
15. **SICUREZZA** → Nessuna API key nel codice. `.env + python-dotenv`.
16. **VERSIONE** → Ogni modulo espone `__version__ = "X.Y.Z"`.
17. **COMMIT** → Conventional Commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`.

## 🌉 LAYER E COMUNICAZIONE
18. **VALUTE** → Ogni importo con `Currency` esplicita. Conversione via `shared/fx_service.py`.
19. **DATE** → Nessuna data naive. UTC internamente, locale in UI.
20. **UI** → Zero valori hardcoded. Tutti da `DESIGN_TOKENS`.
21. **LAYER** → `engine/` ↔ `personal/` SOLO tramite `bridge/api_contracts.py`.
22. **PROFILO** → Ogni suggerimento filtrato da `InvestorProfile`. Zero eccezioni.

## 📊 QUALITÀ ANALITICA
23. **BACKTEST** → Usare `VectorBT`. Zero loop Python su serie temporali. Sempre commissioni, slippage, anti look‑ahead.
24. **STRESS_TEST** → Include: (a) scenari storici, (b) scenari sintetici forward‑looking. Mai solo storici.
25. **LATENCY** → Dati real‑time ≤ 60 secondi. WebSocket dove possibile.
26. **DATA_QUALITY** → Ogni serie temporale ha `DataQualityReport` allegato. `quality_score < 0.5` → warning, non entra in calcoli critici.

## 🛡️ OPERATIVITÀ
27. **DUCKDB_MIGRATIONS** → Ogni modifica schema DuckDB con script SQL in `shared/db/migrations/duckdb/YYYYMMDD_NNN_desc.sql`. Applicate da `DuckDBMigrator.apply_pending()` all’avvio.
28. **RATE_BUDGET** → Ogni fetcher dichiara `RateBudget` in `config/rate_limits.yaml`. `RateLimitManager` è l’unico punto di controllo.
29. **FEATURE_FLAGS** → Funzionalità sperimentali/costose controllate da `config/feature_flags.yaml`. Mai enable per default in test.
30. **ERROR_BUDGET** → SLA: latenza P95 ≤ 2s per query analisi, uptime scheduler ≥ 99%. Se error_rate 5min > 10% → scheduler si auto‑sospende.
31. **DATA_RETENTION** → DuckDB: prezzi 20 anni, macro 30 anni, sentiment 3 anni, quality_reports 1 anno, backtest_results 2 anni. SQLite: posizioni storiche 10 anni, alert_history 1 anno.
32. **AUTH_UI** → UI Streamlit protetta da password via `st.secrets["auth"]["password"]` o `STREAMLIT_AUTH_TOKEN`. Mai dashboard esposta senza autenticazione.