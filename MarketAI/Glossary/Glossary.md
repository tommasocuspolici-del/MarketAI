
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

**DataProvider** – Interfaccia astratta per l'acquisizione di dati finanziari (YFinance, Alpha Vantage, Finnhub).

**Drift Detection** – Monitoraggio della degradazione delle performance di un modello nel tempo. Allerta se MAE supera soglie (WARNING: +20%, CRITICAL: +50%).

**DuckDB** – Database column‑store embedded utilizzato per dati storici di mercato (analitico).

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

**Rate Limiting** – Controllo del numero di richieste a un'API esterna per rispettare i limiti del servizio (es. 5 richieste/minuto per Alpha Vantage).

**Regola 22** – Il profilo investitore filtra TUTTI i suggerimenti provenienti dall'Engine.

**Regola 23** – Commissioni e slippage in backtesting ≥ 0.001 (0.1%). Nessun backtest senza costi.

**Regola 27** – `engine/` e `personal/` non devono importarsi a vicenda. Comunicazione solo via Bridge.

**Regola 28** – Ogni provider dati deve rispettare i rate limit definiti in `config/rate_limits.yaml`.

**Regola 29** – No look‑ahead bias: segnali di backtest shiftati di 1, feature solo laggate.

**Regola 30** – Immutabilità dei dati: le pipeline restituiscono copie, non modificano l'originale.

**Regola 31** – IPC via Bridge: dati scambiati serializzabili tramite contratti definiti in `bridge/api_contracts.py`.

**Regola 32** – Autenticazione API: header X-API-Key per FastAPI.

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