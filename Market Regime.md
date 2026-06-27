# Advanced Metrics — Metriche di Valutazione Avanzate

**File sorgente:** `engine/analytics/evaluation/advanced_metrics.py`
**Introdotto in:** v14 — Modelli Avanzati e Backtesting Realistico (Sessione 4)
**Scopo:** Metriche avanzate per previsioni puntuali e probabilistiche

---

## Panoramica

Le metriche standard (MAE, RMSE, MAPE) non bastano per valutare previsioni finanziarie. `advanced_metrics.py` implementa metriche più sofisticate che catturano: simmetria degli errori, confronto con benchmark naive, accuratezza direzionale con significatività statistica, e qualità delle distribuzioni probabilistiche.

---

## Metriche puntuali

### SMAPE — Symmetric Mean Absolute Percentage Error

```python
from engine.analytics.evaluation.advanced_metrics import smape

val = smape(actual, predicted)
# Range: [0, 200%] — 0% = perfetto
# Simmetrico: penalizza ugualmente over e under-prediction
# Preferibile a MAPE su serie con valori vicini a zero
```

Interpretazione: < 5% = eccellente · 5–15% = buono · 15–30% = accettabile · > 30% = rivedere il modello.

### Theil's U2 — Confronto con Naive Forecast

```python
val = theil_u2(actual, predicted)
# U2 < 1.0  → il modello batte il forecast naive (ultimo valore)  ✅
# U2 = 1.0  → pari al naive
# U2 > 1.0  → peggio del naive → il modello non aggiunge valore  ❌
```

**Regola:** Un modello con Theil's U2 > 1.0 non deve essere pubblicato nella dashboard.

### MDA con Test Binomiale — Mean Directional Accuracy

```python
result = mda_with_significance(actual, predicted)
# result["mda"]:            float [0,1] — % previsioni con direzione corretta
# result["p_value"]:        float — p-value test binomiale (H0: MDA = 0.5)
# result["is_significant"]: bool — True se p_value < 0.05
```

**Interpretazione:** MDA = 0.6 con p_value = 0.03 → il modello prevede la direzione correttamente il 60% delle volte, e questo risultato è statisticamente significativo (non casualità).

### Tail-Weighted Loss

```python
val = tail_weighted_loss(actual, predicted, tail_pct=0.10)
# Media degli errori nel 10% peggiore
# Utile per modelli usati in risk management (errori estremi sono più importanti)
```

---

## Metriche probabilistiche

Valutano la qualità di `ProbabilisticPrediction` (Q10-Q90), non solo della mediana.

### Pinball Loss (Quantile Loss)

```python
val = pinball_loss(actual, predicted_quantile, q=0.10)
# Misura la qualità di un singolo quantile
# Loss asimmetrica: penalizza di più se actual > predicted (underestimate)
# Minore è meglio
```

Calcolo per tutti i quantili:
```python
losses = {
    "q10": pinball_loss(actual, prob.q10, q=0.10),
    "q25": pinball_loss(actual, prob.q25, q=0.25),
    "q50": pinball_loss(actual, prob.q50, q=0.50),  # equivale al MAE pesato
    "q75": pinball_loss(actual, prob.q75, q=0.75),
    "q90": pinball_loss(actual, prob.q90, q=0.90),
}
```

### CRPS — Continuous Ranked Probability Score

```python
val = crps(actual, q10=prob.q10, q50=prob.q50, q90=prob.q90)
# Misura la qualità COMPLESSIVA della distribuzione probabilistica
# Più basso = meglio. CRPS = 0 su previsione perfetta.
# Approssimazione via media delle Pinball Loss su Q10, Q50, Q90
```

Il CRPS è la metrica principale per confrontare modelli probabilistici. Un `EnsemblePredictor` con CRPS più basso batte un singolo modello.

---

## Diagnostica dei residui

Il `DiagnosticReport` fornisce un semaforo automatico sulla qualità del modello.

### Ljung-Box Test — Autocorrelazione residui

```python
from engine.analytics.evaluation.residual_diagnostics import ljung_box_test

result = ljung_box_test(residuals, lags=10)
# result["is_autocorrelated"]: True → i residui hanno pattern non modellati
# Implicazione: aggiungere più lag o cambiare modello
```

### ARCH LM Test — Eteroschedasticità condizionale

```python
result = arch_lm_test(residuals, lags=5)
# result["has_arch_effect"]: True → volatilità clustering non catturata
# Implicazione: aggiungere modello GARCH per la varianza, o pesare gli errori
```

### Jarque-Bera Test — Normalità residui

```python
result = jarque_bera_test(residuals)
# result["is_normal"]: True → residui approssimativamente normali
# is_normal = False: distribuzione con code pesanti (fat tails)
# Implicazione: le bande di confidenza potrebbero essere sottostimate
```

### Semaforo diagnostico automatico

```python
from engine.analytics.evaluation.residual_diagnostics import generate_diagnostic_report

report = generate_diagnostic_report(actual, predicted, model_name="xgboost")
# report["status"]:  "VERDE" | "GIALLO" | "ROSSO"
# report["issues"]:  lista di stringhe con i problemi trovati
# report["tests"]:   dict con risultati test individuali
```

| Stato | Criteri | Azione |
|---|---|---|
| 🟢 VERDE | Nessun test fallisce | Modello OK per produzione |
| 🟡 GIALLO | 1 test fallisce (es. solo non-normalità) | Monitorare, accettabile per uso |
| 🔴 ROSSO | 2+ test falliscono (autocorrelazione + ARCH insieme) | Non usare, rivedere il modello |

---

## Dove vengono usate

| Metrica | Dove appare in dashboard |
|---|---|
| SMAPE, Theil's U2, MDA | Q1 Backtesting — tabella comparativa modelli |
| Pinball Loss per quantile | Q1 Backtesting — sezione "Qualità Previsione Probabilistica" |
| CRPS | Q1 Backtesting — confronto ensemble vs singoli modelli |
| Semaforo diagnostico | Q1 Backtesting — sidebar "Diagnostica Residui" |
| Theil's U2 | S2 Settings — sezione "Salute Modelli" (v15) |

---

## Regola: metrica minima per pubblicare un modello

```
□ Theil's U2 < 1.0          (il modello batte il naive)
□ SMAPE < 15%               (errore accettabile)
□ MDA is_significant = True  (direzione statisticamente significativa)
□ Semaforo diagnostico ≠ ROSSO
□ CRPS calcolabile (almeno 3 quantili disponibili)
```

---

## Test

```
tests/engine/evaluation/test_advanced_metrics.py
  - test_smape_perfect_prediction: SMAPE = 0% su serie identiche
  - test_theil_u2_below_one_for_good_model: U2 < 1 su trend lineare
  - test_theil_u2_above_one_for_naive_model: U2 > 1 su output costante
  - test_mda_significance_on_random: p_value > 0.05 su segnale random
  - test_pinball_loss_asymmetry: loss Q10 > loss Q90 su same error
  - test_crps_zero_on_perfect: CRPS = 0 su previsione esatta
  - test_diagnostic_green_on_white_noise: residui iid → VERDE
  - test_diagnostic_red_on_ar1: residui AR(1) → ROSSO (autocorrelazione)
```

---

## Anti-pattern

```
❌ Metriche calcolate in-sample (sui dati di training)
   → SEMPRE su validation/test set out-of-sample

❌ MAPE usato su serie con valori vicini a zero
   → Usare SMAPE che è simmetrico e stabile su valori piccoli

❌ Confronto modelli con Theil's U2 senza specificare il naive benchmark
   → Il naive di default è "ultimo valore osservato"

❌ Semaforo rosso ignorato per "comodità"
   → Modello con diagnostica ROSSA non deve apparire nelle previsioni live
```

---

## Firma API completa

```python
# engine/analytics/evaluation/advanced_metrics.py

def smape(actual: np.ndarray, predicted: np.ndarray) -> float: ...
def theil_u2(actual: np.ndarray, predicted: np.ndarray) -> float: ...
def mda_with_significance(actual: np.ndarray, predicted: np.ndarray) -> dict: ...
def pinball_loss(actual: np.ndarray, predicted_quantile: np.ndarray, q: float) -> float: ...
def crps(actual: np.ndarray, q10: np.ndarray, q50: np.ndarray, q90: np.ndarray) -> float: ...
def tail_weighted_loss(actual: np.ndarray, predicted: np.ndarray, tail_pct: float = 0.10) -> float: ...

# engine/analytics/evaluation/residual_diagnostics.py

def ljung_box_test(residuals: np.ndarray, lags: int = 10) -> dict: ...
def arch_lm_test(residuals: np.ndarray, lags: int = 5) -> dict: ...
def jarque_bera_test(residuals: np.ndarray) -> dict: ...
def generate_diagnostic_report(actual: np.ndarray, predicted: np.ndarray, model_name: str) -> dict: ...
```

---

## Glossario termini

| Termine | Significato |
|---|---|
| **SMAPE** | Symmetric Mean Absolute Percentage Error — MAPE simmetrico |
| **Theil's U2** | Rapporto MSE modello / MSE naive — < 1 = modello batte naive |
| **MDA** | Mean Directional Accuracy — % previsioni con segno corretto |
| **Pinball Loss** | Loss asimmetrica per valutare quantili — anche detta Quantile Loss |
| **CRPS** | Continuous Ranked Probability Score — qualità distribuzione completa |
| **Ljung-Box** | Test autocorrelazione residui |
| **ARCH LM** | Test eteroschedasticità condizionale (volatility clustering) |
| **Jarque-Bera** | Test normalità distribuzioni (skewness + kurtosis) |

---

## Collegamenti

- [[Probabilistic Prediction]] — il formato Q10-Q90 su cui si calcolano CRPS e Pinball
- [[Forecasting Engine Map]] — dove le metriche si inseriscono nel flusso
- [[Ensemble predictor]] — usa get_metrics() basato su MAE per i pesi
- [[Realistic Backtester]] — metriche backtest (Sharpe, MaxDD) — separate da queste
