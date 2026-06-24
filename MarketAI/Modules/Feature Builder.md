
---
**Introdotto in:** v13 – Modellistica Avanzata (Sessione 4)  
**File sorgente:** `engine/analytics/features/feature_builder.py`  
**Stato:** Pipeline di feature engineering modulare
## Panoramica
`FeatureBuilder` è una pipeline di feature engineering che trasforma dati OHLCV grezzi in feature utilizzabili per modelli di machine learning. Supporta sia la generazione automatica di feature che la configurazione manuale per retrocompatibilità.

## Modalità di funzionamento

### 1. Auto-features (`auto_features=True`)
Genera automaticamente:
- **Lag:** 1, 5, 10, 20 giorni
- **Rolling statistics:** Media, deviazione standard, z-score su finestre 10, 30, 60
- **Fourier features:** Sinusoidi e cosinusoidi per periodi 5, 21, 63 giorni (3 armoniche)
- **Selezione:** Mantiene solo le feature con correlazione ≥ 0.01 con il target, max 50 feature

### 2. Manuale (`auto_features=False`)
L'utente specifica esplicitamente le feature da generare:
```python
builder = FeatureBuilder(auto_features=False)
builder.add_lags([1, 5, 10, 20])
builder.add_rolling(windows=[10, 30])
builder.add_fourier(periods=[5, 21], harmonics=3)
X = builder.fit_transform(df)