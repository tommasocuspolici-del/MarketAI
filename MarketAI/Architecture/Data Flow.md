# Data Flow – Percorso dei Dati attraverso MarketAI

**Introdotto in:** v10 (Architettura base)  
**Ultimo aggiornamento:** v15 (UI Native e Persistenza)  
**Stato:** Documentazione del flusso end‑to‑end

## Panoramica

Il data flow di MarketAI descrive come i dati grezzi di mercato vengono trasformati in previsioni, backtest e dashboard, attraversando i vari layer dell'architettura (Engine, Bridge, Personal, UI). Questo documento mappa ogni passaggio, indicando i moduli coinvolti e le regole di validazione applicate.

```mermaid
graph TD
    A[Data Sources<br/>Yahoo, FRED, SEC, Finnhub] --> B[ProviderRegistry<br/>v12 - fallback automatico]
    B --> C[Data Cleaner<br/>rimozione NaN, outlier, adjust]
    C --> D[FeatureBuilder<br/>v13 - lag, rolling, Fourier]
    D --> E[Model Training<br/>XGBoost, N-BEATS, Ensemble]
    E --> F[ProbabilisticPrediction<br/>v13 - quantili Q10-Q90]
    F --> G[Dashboard Q1<br/>Fan chart, metriche]
    
    E --> H[Realistic Backtester<br/>v14 - commissioni, slippage]
    H --> I[Equity Curve<br/>lordo vs netto]
    I --> G
    
    G --> J[Persistenza Sessioni<br/>v15 - db/user_sessions.db]
    J --> K[Cronologia Analisi<br/>H1_Cronologia.py]
    
    F --> L[FastAPI /predict<br/>v14 - esposizione REST]
    L --> M[Client esterni<br/>curl, Postman, integrazioni]
    
    E --> N[Drift Detector<br/>v15 - monitoraggio performance]
    N --> O[Alert in S2_Settings<br/>semaforo VERDE/GIALLO/ROSSO]
    
    G --> P[pywebview Shell<br/>v15 - UI nativa Windows]
    P --> Q[Utente finale]