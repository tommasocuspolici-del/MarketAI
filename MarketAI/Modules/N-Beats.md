# N-BEATS (Neural Basis Expansion Analysis for Time Series)

**Introdotto in:** v14 – Modelli Avanzati (Sessione 1–2)  
**File sorgente:** `engine/analytics/forecasting/nbeats/`  
**Stato:** Modello DL CPU-first con vincoli hardware

## Panoramica

N-BEATS è un modello di deep learning per time series forecasting introdotto da Oreshkin et al. (2019). È progettato per essere interpretabile grazie alla decomposizione in stack (trend e stagionalità). L'implementazione in MarketAI è ottimizzata per CPU e rispetta i vincoli hardware del sistema (16GB RAM, nessuna GPU stabile).

## Architettura

```mermaid
graph LR
    A[Input: 60 giorni] --> B[Stack Trend]
    A --> C[Stack Seasonality]
    B --> D[Backcast]
    C --> D
    D --> E[Forecast: 30 giorni]