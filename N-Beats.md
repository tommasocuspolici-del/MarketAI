# BaseModel Interface

**File sorgente:** `engine/analytics/forecasting/base_model.py`
**Introdotto in:** v13 — Modellistica Avanzata (Sessione 1)
**Scopo:** Contratto comune che TUTTI i modelli di previsione devono rispettare

---

## Regola fondamentale

Ogni modello in MarketAI eredita da `BaseModel`. Nessun modello viene acceduto direttamente dalle pagine UI o dalla FastAPI — sempre tramite [[Model Registry]].

---

## Interfaccia completa

```python
# engine/analytics/forecasting/base_model.py

class BaseModel(ABC):

    # ─── PROPRIETÀ OBBLIGATORIE ──────────────────────────────────────────
    @property
    @abstractmethod
    def name(self) -> str:
        """Identificatore univoco nel ModelRegistry.
        Esempi: "arima", "xgboost", "nbeats", "ensemble_weighted"
        """
        ...

    # ─── METODI OBBLIGATORI (override richiesto) ─────────────────────────
    @abstractmethod
    def fit(self, train: pd.DataFrame, target_col: str = "Close") -> "BaseModel":
        """Addestra il modello su dati storici.
        Deve ritornare self per chaining: model.fit(df).predict(30)
        Raises:
            FeatureDisabledError: se il modello richiede un feature flag non attivo
            InsufficientMemoryError: se il modello DL richiede più RAM di quella disponibile
        """
        ...

    @abstractmethod
    def predict(self, horizon: int) -> pd.Series:
        """Previsione puntuale (mediana).
        Args:
            horizon: numero di periodi futuri (giorni, se dati daily)
        Returns:
            pd.Series con DatetimeIndex UTC-aware e valori float64
        Raises:
            RuntimeError: se chiamato prima di fit()
        """
        ...

    # ─── METODI CON FALLBACK (override consigliato ma non obbligatorio) ──
    def predict_probabilistic(self, horizon: int) -> "ProbabilisticPrediction":
        """Previsione con quantili Q10-Q25-Q50-Q75-Q90.
        DEFAULT: fallback simmetrico ±10% attorno alla mediana.
        OVERRIDE: XGBoostModel, RandomForestModel (quantile nativa),
                  EnsemblePredictor (combinazione distribuzioni).
        """
        point = self.predict(horizon)
        return ProbabilisticPrediction.from_point_forecast(
            point, uncertainty_pct=0.10, model_name=self.name
        )

    def get_metrics(self, validation: pd.DataFrame,
                    target_col: str = "Close") -> "ModelMetrics":
        """Calcola MAE, RMSE, MAPE, Directional Accuracy su validation set.
        Usato da EnsemblePredictor per il calcolo dei pesi (weighted strategy).
        DEFAULT: implementazione generica basata su predict().
        """
        predictions = self.predict(len(validation))
        actual = validation[target_col].values
        pred   = predictions.values[:len(actual)]
        mae    = float(np.mean(np.abs(actual - pred)))
        rmse   = float(np.sqrt(np.mean((actual - pred) ** 2)))
        mape   = float(np.mean(np.abs((actual - pred) / (actual + 1e-8))) * 100)
        da     = float(np.mean(
            np.sign(np.diff(actual)) == np.sign(np.diff(pred))
        ))
        return ModelMetrics(mae=mae, rmse=rmse, mape=mape,
                            directional_accuracy=da,
                            validation_start=str(validation.index[0]),
                            validation_end=str(validation.index[-1]))

    def is_available(self) -> bool:
        """True se il modello è utilizzabile nella sessione corrente.
        DEFAULT: True sempre.
        OVERRIDE: NBeatsModel (controlla feature flag + RAM disponibile).
        """
        return True
```

---

## Dataclass di supporto

```python
@dataclass
class ModelMetrics:
    mae:                   float    # Mean Absolute Error
    rmse:                  float    # Root Mean Square Error
    mape:                  float    # Mean Absolute Percentage Error (%)
    directional_accuracy:  float    # % volte che la direzione è corretta [0,1]
    validation_start:      str      # ISO date
    validation_end:        str      # ISO date
```

---

## Tabella: cosa implementare in un nuovo modello

| Metodo | Obbligatorio | Note |
|---|---|---|
| `name` | ✅ sì | Stringa univoca, lowercase, no spazi |
| `fit()` | ✅ sì | Sempre ritorna `self` |
| `predict()` | ✅ sì | DatetimeIndex UTC-aware |
| `predict_probabilistic()` | ⚠️ consigliato | Se non override → fallback ±10% |
| `get_metrics()` | ⚠️ consigliato | Se non override → implementazione generica |
| `is_available()` | Solo se condizionale | N-BEATS, modelli GPU |

---

## Vincoli su `fit()`

```python
def fit(self, train: pd.DataFrame, target_col: str = "Close") -> "BaseModel":
    # ── Checklist pre-training ────────────────────────────────────────
    # 1. Il DataFrame ha DatetimeIndex UTC-aware?
    assert train.index.tz is not None, "DatetimeIndex deve essere UTC-aware"
    # 2. La colonna target esiste?
    assert target_col in train.columns, f"Colonna '{target_col}' non trovata"
    # 3. Nessun NaN nel target? (DataCleaner deve aver già agito)
    assert not train[target_col].isna().any(), "NaN trovati — passare per DataCleaner"
    # 4. Feature flag attivo se necessario? (solo modelli sperimentali)
    # require_enabled("nbeats_model")  ← solo in NBeatsModel
    # 5. RAM sufficiente? (solo modelli DL pesanti)
    # require_ram(min_gb=4.0)  ← solo in NBeatsModel
    ...
```

---

## Vincoli su `predict()`

```python
def predict(self, horizon: int) -> pd.Series:
    # ── Output obbligatorio ───────────────────────────────────────────
    # 1. pd.Series con DatetimeIndex business-day aware (o freq del training)
    # 2. Index con timezone UTC
    # 3. Valori float64 (mai float32 per risultati finali — R8)
    # 4. Len(result) == horizon
    ...
    # Esempio costruzione index futuro:
    last_date  = self._train_index[-1]
    future_idx = pd.date_range(
        start=last_date + pd.Timedelta(days=1),
        periods=horizon,
        freq="B",      # business days
        tz="UTC"
    )
    return pd.Series(predictions.astype(np.float64), index=future_idx)
```

---

## Template nuovo modello

```python
# engine/analytics/forecasting/my_model.py
"""MyModel: descrizione concisa.
Prerequisiti: nessuno / feature flag X / RAM ≥ Y GB
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from engine.analytics.forecasting.base_model import BaseModel, ModelMetrics
from engine.analytics.forecasting.probabilistic_prediction import ProbabilisticPrediction

class MyModel(BaseModel):
    """Implementazione concreta di BaseModel."""

    def __init__(self, param1: int = 5) -> None:
        self._param1 = param1
        self._fitted = False

    @property
    def name(self) -> str:
        return "my_model"

    def fit(self, train: pd.DataFrame, target_col: str = "Close") -> "MyModel":
        # validazione input
        # training logic
        self._fitted = True
        return self

    def predict(self, horizon: int) -> pd.Series:
        if not self._fitted:
            raise RuntimeError("Chiamare fit() prima di predict()")
        # prediction logic
        values = np.zeros(horizon, dtype=np.float64)   # placeholder
        idx = pd.date_range(start="2024-01-01", periods=horizon, freq="B", tz="UTC")
        return pd.Series(values, index=idx)

    # predict_probabilistic() → ereditato (fallback ±10%)
    # get_metrics()           → ereditato (implementazione generica)
    # is_available()          → ereditato (sempre True)
```

---

## Checklist per aggiungere un modello nuovo

```
□ Eredita da BaseModel (non da una classe concreta)
□ name: stringa unica — verificare che non esista già nel ModelRegistry
□ fit(): ritorna self, accetta target_col parametrizzato
□ predict(): DatetimeIndex UTC-aware, float64, len == horizon
□ Test: tests/engine/forecasting/test_<nome>.py con dati sintetici
□ Registrazione in ModelRegistry (app_unified.py o init_providers.py)
□ Feature flag se sperimentale (config/feature_flags.yaml: false default)
□ Aggiornare Forecasting Engine Map.md tabella "quale modello implementa cosa"
□ pytest -m regression: 0 failed
```

---

## Errori comuni

| Errore | Causa | Fix |
|---|---|---|
| `RuntimeError: fit() before predict()` | predict() chiamato senza fit() | Aggiungere guard `if not self._fitted` |
| `AssertionError: DatetimeIndex UTC` | Index senza timezone | `.tz_localize("UTC")` o `.tz_convert("UTC")` |
| `TypeError: float32` in output | `astype(np.float32)` nel codice | Cambiare in `np.float64` |
| `KeyError` in ModelRegistry | Nome non registrato | Aggiungere a init dell'app |

---

## Relazioni con altri moduli

```
BaseModel ←── eredita ─── ARIMAModel, ProphetModel, XGBoostModel
                       ─── RandomForestModel, NBeatsModel
                       ─── EnsemblePredictor
BaseModel ───→ usa ──→ ProbabilisticPrediction (output)
BaseModel ───→ usa ──→ ModelMetrics (valutazione)
ModelRegistry ──→ contiene ──→ [istanze di BaseModel]
```

---

## Collegamenti

- [[Model Registry]] — dove i modelli vengono registrati e acceduti
- [[Forecasting Engine Map]] — panoramica del sistema di previsione
- [[Ensemble predictor]] — usa get_metrics() per calcolare i pesi
- [[Probabilistic Prediction]] — output di predict_probabilistic()
- [[N-Beats]] — esempio modello con is_available() condizionale
