# Engine Layer – Motore di Analisi Quantitativa

**Introdotto in:** v10 (Architettura base)  
**File principali:** `engine/` (intera cartella)  
**Stato:** Nucleo computazionale del sistema

## Panoramica

L'**Engine Layer** è il cervello quantitativo di MarketAI. Si occupa di acquisire dati di mercato, trasformarli in feature, addestrare modelli previsivi, eseguire backtest e valutare le performance. È progettato per essere modulare, testabile e indipendente dal **Personal Layer** (finanze personali), con cui comunica esclusivamente tramite il [[Bridge Overview|Bridge]].

```mermaid
graph TB
    subgraph Engine[Engine Layer]
        direction TB
        DP[Data Provider System<br/>v12] --> FB[FeatureBuilder<br/>v13]
        FB --> MOD[Modelli Previsivi<br/>ARIMA, XGBoost, N-BEATS]
        MOD --> ENS[Ensemble Predictor<br/>v13]
        MOD --> PROB[ProbabilisticPrediction<br/>v13]
        MOD --> BT[Realistic Backtester<br/>v14]
        BT --> EVAL[Metriche Avanzate<br/>SMAPE, CRPS, Drift]
    end
    
    Bridge[Bridge<br/>api_contracts.py] -.-> Engine
    Engine -.-> FastAPI[FastAPI Backend<br/>v14]