
# Glossary – Glossario dei Termini Tecnici

**Ultimo aggiornamento:** v15 – UI Native
## A

**Alpha Generation** – Modulo dell'Engine che genera segnali di trading basati su modelli quantitativi (sentiment, momentum, value, etc.).

**ARCH LM Test** – Test statistico per verificare la presenza di eteroschedasticità condizionale (volatility clustering) nei residui di un modello.

**ARIMA** – AutoRegressive Integrated Moving Average. Modello statistico per time series forecasting.

## B

**Backtesting** – Simulazione di una strategia di trading su dati storici per valutare le performance.

**BaseModel** – Interfaccia astratta che tutti i modelli di previsione devono implementare (fit, predict, predict_probabilistic, get_metrics).

**Bridge** – Layer di comunicazione tra Engine e Personal. Definisce i contratti API (`api_contracts.py`).

## C

**Circuit Breaker** – Pattern di resilienza che interrompe le chiamate a un servizio dopo un numero di fallimenti consecutivi.

**CRPS** – Continuous Ranked Probability Score. Misura la qualità di una previsione probabilistica (più basso = meglio).

## D

**DataCleaner** – Orchestratore che applica gap filling, outlier detection, stale detection a dati grezzi PRIMA della validazione Pandera. Tappa obbligatoria della pipeline.

**DataProvider** – Interfaccia astratta per l'acquisizione di dati finanziari (YFinanceProvider, AlphaVantageProvider, FinnhubProvider).

**DataQualityReport** – Oggetto con score [0,1] della qualità di una serie temporale. Score < 0.5 = non usare in calcoli critici. Allegato ad ogni dato che entra nel sistema.

**Drift Detection** – Monitoraggio della degradazione delle performance di un modello nel tempo. Allerta se MAE supera soglie (WARNING: +20%, CRITICAL: +50%).

**DuckDB** – Database column-store embedded per dati storici di mercato (analitico/OLAP). NON usare per dati transazionali.

**DuckDBMigrator** – Componente che gestisce l'evoluzione dello schema DuckDB tramite file SQL versionati (simile a Flyway). `apply_pending()` chiamato all'avvio.

## E

**Ensemble Predictor** – Modello che combina le previsioni di più modelli base (media, pesata, stacking).

**Equity Curve** – Grafico dell'evoluzione del capitale nel tempo durante un backtest (lorda vs netta).

## F

**Fan Chart** – Grafico che mostra l'incertezza di una previsione tramite bande di quantili (Q10‑Q90).

**FeatureBuilder** – Pipeline di feature engineering modulare (lag, rolling stats, Fourier, selezione automatica).

**Feature Flags** – Configurazioni booleane per abilitare/disabilitare moduli sperimentali o pesanti.

**FIRE** – Financial Independence, Retire Early. Calcolo dell'età di pensionamento basato su patrimonio e spese.

## G

**Graceful Degradation** – Capacità del sistema di continuare a funzionare (anche in modo limitato) quando un componente fallisce.

## H

**Health Check** – Endpoint `/health` che verifica lo stato del sistema (database, API, modelli).

## J

**Jarque-Bera Test** – Test statistico per verificare la normalità dei residui di un modello.

## L

**Ljung-Box Test** – Test statistico per verificare l'autocorrelazione dei residui di un modello.

## M

**MDA** – Mean Directional Accuracy. Percentuale di previsioni che indovinano la direzione del movimento.

**Monte Carlo Simulation** – Simulazione di 10.000 scenari patrimoniali per valutare la probabilità di successo di un piano finanziario.

**Mypy** – Type checker statico per Python (strict mode).

## N

**N‑BEATS** – Neural Basis Expansion Analysis for Time Series. Modello DL per forecasting con decomposizione trend/stagionalità.

**Net Worth** – Patrimonio netto = Totale Attività – Totale Passività.

## P

**Pinball Loss** – Funzione di loss asimmetrica per valutare previsioni quantiliche.

**ProbabilisticPrediction** – Formato unificato per previsioni con quantili (Q10, Q25, Q50, Q75, Q90).

**ProviderRegistry** – Singleton che gestisce i DataProvider, priorità e fallback automatico.

**pywebview** – Libreria che crea finestre native (Windows, macOS, Linux) per incapsulare applicazioni web.

## Q

**Quantile Regression** – Tecnica di regressione che stima i quantili condizionali della variabile target (Q10, Q50, Q90, etc.).

## R

**RateBudget** – Configurazione dei limiti di chiamate API per una sorgente (req/min, req/day). Letto da `config/rate_limits.yaml`.

**RateLimitManager** – Componente centralizzato (singleton) che throttla le richieste API nel rispetto dei budget dichiarati. Unico punto di controllo. Ogni fetcher chiama `acquire(source)` prima di qualsiasi chiamata API.

**Regola 21 (LAYER)** – `engine/` ↔ `personal/` SOLO tramite `bridge/api_contracts.py`. Nessun import diretto.

**Regola 22 (PROFILO)** – Il profilo investitore (`InvestorProfile`) filtra TUTTI i suggerimenti. Zero eccezioni.

**Regola 23 (BACKTEST)** – Commissioni ≥ 0.001, slippage ≥ 0.001, segnali shift(1). Nessun backtest senza costi.

**Regola 27 (DUCKDB_MIGRATIONS)** – Schema DuckDB: modifiche SOLO via script SQL in `shared/db/migrations/duckdb/`. YYYYMMDD_NNN_descrizione.sql. Mai modificare schema manualmente.

**Regola 28 (RATE_BUDGET)** – Ogni fetch esterno usa `RateLimitManager.acquire(source)`. Nessun bypass.

**Regola 29 (FEATURE_FLAGS)** – Feature sperimentali/costose controllate da `config/feature_flags.yaml` (default: false).

**Regola 30 (ERROR_BUDGET)** – SLA interni: latenza P95 ≤ 2s; uptime scheduler ≥ 99%. Se error_rate > 10% → scheduler auto-sospende.

**Regola 31 (DATA_RETENTION)** – DuckDB: prezzi 20 anni; macro 30 anni; SQLite: posizioni 10 anni.

**Regola 32 (AUTH_UI)** – Dashboard protetta da password. `STREAMLIT_AUTH_ENABLED=true` in produzione.

**Regola 33** – Dati personali sensibili: mai esposti via API senza autenticazione esplicita.

## S

**SMAPE** – Symmetric Mean Absolute Percentage Error. Metrica di errore simmetrica [0, 200%].

**SMART** – Specific, Measurable, Achievable, Relevant, Time‑bound. Criteri per definire obiettivi finanziari.

**Slippage** – Differenza tra prezzo atteso e prezzo effettivamente eseguito in un ordine di trading.

**SQLite** – Database relazionale embedded utilizzato per dati transazionali e preferenze utente.

**Stacking** – Strategia di ensemble che usa un meta‑modello (Ridge) per combinare le previsioni dei modelli base.

## T

**Theil's U2** – Metrica che confronta il modello con una previsione naive (ultimo valore). U2 < 1 = modello batte naive.

**Tray Icon** – Icona nella system tray di Windows che permette di controllare MarketAI (Management UI).

## U

**UI Native** – Applicazione Windows senza browser visibile, implementata con pywebview.

## V

**VectorBT** – Libreria di backtesting veloce usata per test preliminari (prima del Realistic Backtester).

**Vibecoding** – Workflow di sviluppo con Claude Code Pro in sessioni brevi (1–2h) con prompt strutturati e checklist.

## W

**WebView2** – Controllo browser di Microsoft Edge utilizzato da pywebview su Windows.

## X

**XGBoost** – Extreme Gradient Boosting. Modello ML con supporto nativo per quantile regression.

## Collegamenti

- [[Architecture Overview]]
- [[Engine Overview]]
- [[Personal Overview]]
- [[Shared Overview]]
- [[Bridge Overview]]
- [[Data Flow]]
---

## Termini aggiunti — Vault v2 (Giugno 2026)

| Termine | Definizione |
|---|---|
| **Advanced Metrics** | Metriche avanzate per valutazione previsioni: SMAPE, Theil's U2, MDA, Pinball Loss, CRPS |
| **ARCH LM Test** | Test per eteroschedasticità condizionale (volatility clustering) nei residui |
| **BaseModel** | ABC (Abstract Base Class) da cui ereditano tutti i modelli di previsione MarketAI |
| **Bugfix Protocol** | Procedura a 5 step: input errore → routing → test riproduzione → fix → classificazione |
| **CRPS** | Continuous Ranked Probability Score — misura qualità complessiva di una previsione probabilistica |
| **Contrarian Signal** | Segnale di trading che va contro il sentiment estremo: score < 20 → BUY; score > 80 → SELL |
| **Custom Indicator DSL** | Mini-linguaggio per definire indicatori tecnici personalizzati (SMA, EMA, RSI, formule aritmetiche) |
| **DCC-GARCH** | Dynamic Conditional Correlation GARCH — stima correlazioni varianti nel tempo tra asset |
| **Diagnostica Residui** | Analisi statistica dei residui del modello: Ljung-Box (autocorrelazione), ARCH LM, Jarque-Bera |
| **Forecasting Engine Map** | Documento architetturale che mappa le relazioni tra tutti i moduli del sistema di previsione |
| **FRED** | Federal Reserve Economic Data — database 600+ serie macroeconomiche (St. Louis Fed) |
| **Granger Causality** | Test statistico che verifica se una serie temporale anticipa (causa) un'altra |
| **HMM** | Hidden Markov Model — modello per classificare il mercato in regimi latenti (bull/bear/transition/stress) |
| **Jarque-Bera** | Test di normalità per residui basato su skewness e kurtosis |
| **Ljung-Box** | Test per autocorrelazione dei residui su multiple lag |
| **Market Regime** | Stato discreto del mercato identificato da HMM: bull / bear / transition / stress |
| **MDA** | Mean Directional Accuracy — percentuale di previsioni con direzione corretta |
| **Model Registry** | Singleton che gestisce la registrazione e il lookup di tutti i modelli di previsione |
| **Pinball Loss** | Loss asimmetrica per valutare la qualità di un quantile specifico (es. Q10, Q90) |
| **Portfolio Optimization** | Ottimizzazione dei pesi di portafoglio tramite CVXPY: max Sharpe, min CVaR, frontiera efficiente |
| **Regime-Conditional Correlation** | Matrice di correlazione calcolata separatamente per ogni regime di mercato |
| **Rebalancing** | Operazione di riallineamento dei pesi di portafoglio al target — suggerita da RebalancingAdvisor |
| **Risk Routing** | Mappatura dal testo di un errore al modulo di codice probabilmente responsabile |
| **SMAPE** | Symmetric Mean Absolute Percentage Error — versione simmetrica del MAPE |
| **Suitability Check** | Verifica che uno strumento finanziario sia compatibile con l'InvestorProfile dell'utente |
| **Theil's U2** | Metrica che confronta il modello con il naive forecast (U2 < 1 = modello batte il naive) |
| **Tail-Weighted Loss** | Media degli errori nel worst-case percentile — utile per risk management |
