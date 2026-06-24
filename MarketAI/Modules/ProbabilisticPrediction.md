# ProbabilisticPrediction

**Introdotto in:** v13 – Modellistica Avanzata (Sessione 1)  
**File sorgente:** `engine/analytics/forecasting/probabilistic_prediction.py`  
**Stato:** Core data structure (immutabile)

## Panoramica

`ProbabilisticPrediction` è il formato unificato per rappresentare previsioni con incertezza in tutto il sistema MarketAI. Ogni modello (ARIMA, Prophet, XGBoost, Ensemble, N‑BEATS) deve restituire un oggetto di questo tipo quando viene chiamato il metodo `predict_probabilistic()`.

Questo oggetto garantisce che le bande di incertezza (fan chart) siano sempre disponibili e validate, indipendentemente dal modello sottostante.

## Attributi principali

| Attributo | Tipo | Descrizione |
|-----------|------|-------------|
| `dates` | `pd.DatetimeIndex` | Indice temporale delle previsioni (future) |
| `q10`, `q25`, `q50`, `q75`, `q90` | `np.ndarray` | Percentili 10, 25, 50 (mediana), 75, 90 |
| `model_name` | `str` | Nome del modello che ha generato la previsione |
| `target_col` | `str` | Colonna prevista (di solito `"Close"`) |

**Regola di validazione:** In fase di inizializzazione (`__post_init__`), viene verificato che i quantili siano monotonicamente crescenti (`q10 ≤ q25 ≤ q50 ≤ q75 ≤ q90`). Se la regola è violata, viene sollevata un'eccezione `AssertionError`.

## Metodi principali

- **`from_point_forecast(forecast: pd.Series, uncertainty_pct: float = 0.10, model_name: str = "unknown") -> ProbabilisticPrediction`**  
  *Fallback universale.* Crea una distribuzione simmetrica attorno a una previsione puntuale. Utilizzato quando un modello non supporta nativamente i quantili (es. vecchie versioni di modelli DL o fallback di sicurezza).

- **`to_dataframe() -> pd.DataFrame`**  
  Converte l'oggetto in un DataFrame pandas con colonne `date, q10, q25, q50, q75, q90, model`. Utile per esportare dati o per il plotting con librerie come Plotly.

## Utilizzo tipico nel codice

```python
from engine.analytics.forecasting.probabilistic_prediction import ProbabilisticPrediction

# Generazione da un modello
model = XGBoostModel()
model.fit(train_df)
prediction = model.predict_probabilistic(horizon=30)

# Accesso rapido
mediana = prediction.q50
banda_inferiore = prediction.q10
banda_superiore = prediction.q90

# Conversione per il plot
df_plot = prediction.to_dataframe()