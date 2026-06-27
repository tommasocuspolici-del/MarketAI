# Modulo di Previsione Probabilistica

Questo modulo estende i modelli deterministici (come N-Beats o TFT) per produrre previsioni probabilistiche, ovvero distribuzioni di probabilità sugli output futuri. Ciò è essenziale per la gestione del rischio e per generare i "fan chart" visualizzati nell'UI.
## Concetti Chiave
- **Quantili**: Produciamo previsioni per diversi quantili (es. Q10, Q20, ..., Q90) che definiscono intervalli di confidenza.
- **CRPS (Continuous Ranked Probability Score)**: Metrica di valutazione che misura la qualità di una previsione probabilistica. Un CRPS più basso indica una migliore calibrazione.
- **Ensemble di Modelli**: Combina le uscite di più modelli (es. N-Beats, TFT, Regressione Quantile) per ottenere una distribuzione più robusta.
## Implementazione Attuale
- Il metodo `predict_probabilistic(symbol, horizon)` restituisce un dizionario con:
  - `quantiles`: dict {quantile: lista di valori per ogni step}.
  - `mean`: previsione media (deterministica).
  - `std`: deviazione standard stimata per ogni step.
- Utilizza un approccio bootstrap per stimare l'incertezza quando i modelli non forniscono direttamente gli intervalli.
- La configurazione (numero di quantili, metodi di ensemble) è in `Configuration/model_params.yaml`.
## Integrazione con il Backtesting
- Durante il backtesting, il CRPS viene calcolato su un orizzonte temporale e registrato come metrica di performance.
- I risultati sono confrontati con un modello naive (es. random walk) per validare il miglioramento.
## Esempio di Output (JSON)
```json
{
  "symbol": "AAPL",
  "horizon": 30,
  "quantiles": {
    "0.1": [150.2, 151.3, ...],
    "0.5": [153.4, 154.5, ...],
    "0.9": [156.7, 158.0, ...]
  },
  "mean": [153.4, 154.5, ...],
  "std": [2.1, 2.3, ...]
}