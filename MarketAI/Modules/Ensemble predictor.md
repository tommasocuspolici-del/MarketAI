# Ensemble Predictor

**Introdotto in:** v13 – Modellistica Avanzata (Sessione 3)  
**File sorgente:** `engine/analytics/forecasting/ensemble_predictor.py`  
**Stato:** Modulo di combinazione di modelli

## Panoramica

`EnsemblePredictor` combina le previsioni di più modelli `BaseModel` per migliorare l'accuratezza e la robustezza. Supporta tre strategie di combinazione: media semplice, pesata per performance, e stacking (meta-modello). L'ensemble eredita da `BaseModel` e può essere utilizzato in tutte le dashboard e API come un modello normale.

## Strategie di combinazione

### 1. Simple Average
- **Logica:** Media aritmetica delle previsioni puntuali di tutti i modelli.
- **Vantaggi:** Semplice, robusto, riduce la varianza.
- **Svantaggi:** Non sfrutta le differenze di performance tra modelli.

### 2. Weighted (performance-based)
- **Logica:** Pesi inversamente proporzionali al MAE su una finestra di validazione recente (default 90 giorni).
- **Formula:** `peso_i = (1 / MAE_i) / sum(1 / MAE_j)`
- **Vantaggi:** Modelli più precisi contribuiscono di più.
- **Aggiornamento:** I pesi vengono ricalcolati automaticamente ad ogni `fit()`.

### 3. Stacking
- **Logica:** Meta-modello Ridge addestrato sulle previsioni dei modelli base su out-of-time validation.
- **Vantaggi:** Può correggere bias sistematici dei modelli base.
- **Svantaggi:** Richiede più dati e tempo di addestramento.
## Come combina le distribuzioni probabilistiche

- **Weighted:** Combina i quantili con gli stessi pesi usati per la previsione puntuale.
    
- **Simple Average:** Media aritmetica di Q10, Q25, Q50, Q75, Q90.
    
- **Stacking:** Usa il meta-modello solo per Q50; per Q10 e Q90 usa l'approccio weighted.
    
**Regola:** `ProbabilisticPrediction` generato dall'ensemble deve sempre avere quantili monotonici (`q10 ≤ q25 ≤ q50 ≤ q75 ≤ q90`).
## Test e qualità
- **Test sintetici:** L'ensemble deve battere il modello peggiore su serie AR(1) e GBM.
    
- **Copertura:** 100% su `ensemble_predictor.py`.
    
- **Performance:** Fit di 3 modelli su 10 anni di dati giornalieri < 60 secondi (CPU).

## Collegamenti

- [[v13 Modeling]] – Sessione 3
    
- [[BaseModel]]
    
- [[ProbabilisticPrediction]]
    
- [[Model Registry]]





## Interfaccia

```python
from engine.analytics.forecasting.ensemble_predictor import EnsemblePredictor

ensemble = EnsemblePredictor(
    models=[arima_model, xgboost_model, prophet_model],
    strategy="weighted",           # "simple_average" | "weighted" | "stacking"
    validation_window_days=90,
)
ensemble.fit(train_df)
prediction = ensemble.predict_probabilistic(horizon=30)
