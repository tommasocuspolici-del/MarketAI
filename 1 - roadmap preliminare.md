# Model Registry

**Introdotto in:** v13 – Modellistica Avanzata (Sessione 1)
**File sorgente:** `engine/analytics/forecasting/model_registry.py`
**Stato:** Singleton per la gestione e il lookup dei modelli di previsione

---

## Panoramica

`ModelRegistry` è il punto di accesso centralizzato a tutti i modelli di previsione di MarketAI. Funziona come un registro a runtime che permette alle pagine dashboard, alla FastAPI e all'EnsemblePredictor di accedere ai modelli disponibili senza conoscere le loro implementazioni concrete.

Segue il pattern **Singleton** per garantire che i modelli siano registrati e inizializzati una sola volta per sessione.

---

## Interfaccia pubblica

```python
from engine.analytics.forecasting.model_registry import ModelRegistry

# Accesso al singleton
registry = ModelRegistry.get_instance()

# Registrare un modello
registry.register(XGBoostModel(), name="xgboost")
registry.register(ARIMAModel(), name="arima")
registry.register(NBeatsModel(), name="nbeats")          # solo se feature flag attivo
registry.register(EnsemblePredictor([...]), name="ensemble_weighted")

# Elenco modelli disponibili (rispetta feature flags)
names = registry.list_names()
# → ["arima", "xgboost", "prophet", "ensemble_weighted"]
# nbeats non compare se feature_flags.yaml: nbeats_model: false

# Recuperare un modello specifico
model = registry.get("xgboost")        # → XGBoostModel instance
model = registry.get("nbeats")         # → NBeatsModel oppure KeyError se disabilitato

# Verificare disponibilità
registry.is_available("nbeats")        # → True/False in base a feature flag + RAM
```

---

## Convenzioni di naming

| Nome nel registry | Classe | Feature flag richiesto |
|---|---|---|
| `"arima"` | `ARIMAModel` | nessuno (sempre disponibile) |
| `"prophet"` | `ProphetModel` | nessuno |
| `"xgboost"` | `XGBoostModel` | nessuno |
| `"random_forest"` | `RandomForestModel` | nessuno |
| `"nbeats"` | `NBeatsModel` | `nbeats_model: true` + RAM ≥ 4GB libera |
| `"ensemble_average"` | `EnsemblePredictor(strategy="simple_average")` | `ensemble_predictor: true` |
| `"ensemble_weighted"` | `EnsemblePredictor(strategy="weighted")` | `ensemble_predictor: true` |
| `"ensemble_stacking"` | `EnsemblePredictor(strategy="stacking")` | `ensemble_predictor: true` |

---

## Dove e come viene popolato

Il registry viene popolato **una sola volta all'avvio** dell'applicazione, in `scripts/init_providers.py` o nell'`app_unified.py`:

```python
# app_unified.py (o script di init)
from engine.analytics.forecasting.model_registry import ModelRegistry
from engine.analytics.forecasting.base_model import BaseModel
from shared.feature_flags import is_enabled
from engine.analytics.forecasting.nbeats.ram_check import available_ram_gb

registry = ModelRegistry.get_instance()

# Modelli base (sempre registrati)
registry.register(ARIMAModel(), name="arima")
registry.register(ProphetModel(), name="prophet")
registry.register(XGBoostModel(), name="xgboost")
registry.register(RandomForestModel(), name="random_forest")

# N-BEATS: solo se feature flag + RAM disponibile
if is_enabled("nbeats_model") and available_ram_gb() >= 4.0:
    registry.register(NBeatsModel(hidden_size=128), name="nbeats")

# Ensemble: solo se feature flag attivo
if is_enabled("ensemble_predictor"):
    base_models = [registry.get("arima"), registry.get("xgboost"), registry.get("prophet")]
    registry.register(
        EnsemblePredictor(base_models, strategy="weighted"),
        name="ensemble_weighted"
    )
```

---

## Utilizzo nelle pagine dashboard

```python
# In Q1_Backtesting.py
from engine.analytics.forecasting.model_registry import ModelRegistry

registry = ModelRegistry.get_instance()
available = registry.list_names()

model_choice = st.selectbox("Modello previsione", options=available, index=0)

if st.button("📊 Genera previsione"):
    model = registry.get(model_choice)
    model.fit(df_train)
    prob = model.predict_probabilistic(horizon=30)
    # → ProbabilisticPrediction con Q10-Q90
```

---

## Utilizzo dalla FastAPI

```python
# api/routes/models.py
from engine.analytics.forecasting.model_registry import ModelRegistry

@router.get("/")
async def list_models():
    registry = ModelRegistry.get_instance()
    return {"models": registry.list_names()}

@router.post("/predict")
async def predict(req: PredictRequest):
    registry = ModelRegistry.get_instance()
    model = registry.get(req.model_name)
    model.fit(train_data)
    return model.predict_probabilistic(req.horizon_days).to_dataframe().to_dict()
```

---

## Regole di progettazione

- Il registry è **read-only dopo l'init**: i modelli vengono registrati una volta all'avvio e non rimossi a runtime.
- `list_names()` restituisce **solo i modelli effettivamente disponibili** (feature flag attivo + RAM ok): mai nomi di modelli che poi fallirebbero a runtime.
- Ogni modello nel registry ha già superato `require_enabled()` al momento della registrazione.
- Il registry NON addestra i modelli: `fit()` viene chiamato dal chiamante con i dati specifici del ticker/periodo.

---

## Test

```
tests/engine/forecasting/
  test_model_registry.py     ← registrazione, list_names, get, feature flag rispettati
```

```python
def test_registry_respects_feature_flag(mock_feature_flags_disabled):
    """Se nbeats_model: false, nbeats non appare in list_names()."""
    registry = ModelRegistry.get_instance()
    # NBeatsModel NON registrato (feature flag off)
    assert "nbeats" not in registry.list_names()

def test_registry_get_unknown_raises():
    with pytest.raises(KeyError):
        ModelRegistry.get_instance().get("modello_inesistente")
```

---

## Collegamenti

- [[BaseModel Interface]] — interfaccia che ogni modello deve implementare
- [[Ensemble predictor]] — usa il registry per accedere ai modelli base
- [[Forecasting Engine Map]] — mappa relazioni tra tutti i moduli forecasting
- [[Feature Builder]] — usato dai modelli ML per le feature
- [[N-Beats]] — modello DL registrato condizionalmente
