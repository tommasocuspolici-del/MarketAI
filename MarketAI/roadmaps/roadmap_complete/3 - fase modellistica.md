# 🟢 ROADMAP — MarketAI v13.0.0 · Fase 2: Modellistica Avanzata
> **v12.0.0 → v13.0.0** · Ensemble · Incertezza · Feature Engineering Automatizzato  
> Prerequisito: v12.0.0 completato (ProviderRegistry · Logging JSON · CI/CD)  
> Pianificazione: Claude Sonnet 4.6 · Implementazione: Claude Code Pro (Opus 4.8)  
> Sessioni: 6 sessioni · Durata stimata: 1–2h ciascuna · Totale: ~4 settimane

---

## 📊 Stato Pre-Fase 2

| Parametro | Valore |
|-----------|--------|
| Versione base | v12.0.0 (provider system + CI/CD attivi) |
| Hardware | Ryzen 5 5600 · RX 6700 8GB VRAM · 16GB RAM · 512GB NVMe |
| GPU note | RX 6700 → ROCm su Windows non stabile; PyTorch su CPU per ora |
| Python venv | 3.12.10 (Poetry) |
| Modelli attuali | ARIMA · Prophet · RF · XGBoost · LSTM · CNN-LSTM · Transformer |
| Gap principali | Nessun ensemble · No incertezza ML · Feature statiche |

---

## 🎯 Obiettivi v13.0.0

### Obbligatori

```
[OB-1] Ensemble Engine
        · EnsemblePredictor con 3 strategie (media, pesata, stacking)
        · Interfaccia identica ai modelli singoli
        · Pesi aggiornati automaticamente su finestra validazione recente

[OB-2] Quantile Forecasting per modelli ML
        · XGBoost: quantile regression (Q10, Q25, Q50, Q75, Q90)
        · Random Forest: quantile regression con sklearn
        · Formato unificato ProbabilisticPrediction
        · Fan chart in dashboard Q1 Backtesting

[OB-3] Feature Engineering Automatizzato
        · FeatureBuilder con flag auto_features=True/False
        · Lag automatici, rolling statistics, Fourier seasonality
        · Selezione feature con importanza (backward elimination)
        · Retrocompatibilità con feature set manuale attuale
```

### Facoltativi (solo se OB-1/2/3 completi e rimane tempo)

```
[OPT-1] Monte Carlo Dropout per LSTM (incertezza DL)
[OPT-2] Autoencoder per feature learning (richiede GPU stabile)
[OPT-3] Integrazione tsfresh (pesante: valutare su 16GB RAM)
```

---

## ⚠️ Vincoli Hardware — CRITICO

```
RAM: 16GB totali
  · LSTM training su 10 anni × 500 ticker → può saturare RAM
  · Limitare batch size a 32 per LSTM
  · tsfresh su serie > 5000 punti → potenzialmente lento, usare feature_calculators subset

GPU (RX 6700 8GB VRAM):
  · ROCm su Windows 11 non ufficialmente supportato
  · PyTorch → modalità CPU per ora (feature flag pytorch_gpu: false)
  · Ollama: verifica compatibilità ROCm prima di abilitare
  · VRAM da usare solo per inferenza (non training in questa fase)

SSD NVMe 512GB:
  · DuckDB + modelli salvati: stimare ~50GB massimo per dati storici 20 anni
  · Backup ZIP compressi: ~2-5GB per snapshot progetto

REGOLA: Nessun modello DL viene abilitato di default (feature_flags.yaml).
         L'utente attiva esplicitamente i modelli pesanti.
```

---

## 🧩 Anti-Pattern Vietati v13.0.0

```
❌ EnsemblePredictor che importa direttamente i modelli base
   → Usa interfaccia BaseModel.predict() sempre

❌ Pesi ensemble hardcoded
   → Sempre calcolati da performance recente su validation window

❌ ProbabilisticPrediction senza tutti i quantili (Q10..Q90)
   → Oggetto incompleto non deve essere ritornato

❌ FeatureBuilder che modifica il DataFrame originale
   → Sempre ritornare copia; input immutabile

❌ Feature engineering con loop Python su serie storiche
   → numpy vettorizzato sempre (R8 - numpy/scipy)

❌ Modello DL abilitato di default in config
   → feature_flags.yaml: lstm: false, pytorch_forecasting: false

❌ Training su GPU senza verifica ROCm/CUDA disponibile
   → is_gpu_available() check prima di qualsiasi training DL

❌ Test ensemble che usa dati reali di mercato
   → Sempre dati sintetici con pattern noti e controllabili

❌ Sessione Opus senza regression test iniziale
   → Obbligatorio: 0 failed prima di modificare qualsiasi file
```

---

## 📅 SESSIONE 1 — Interfaccia Comune BaseModel e ProbabilisticPrediction (1–2h)

**Obiettivo:** Creare la struttura condivisa da ensemble e modelli probabilistici

**NON toccare:** modelli esistenti in `models/`

**File da creare:**
```
engine/analytics/forecasting/
  base_model.py              ← BaseModel ABC con interfaccia standard
  probabilistic_prediction.py ← ProbabilisticPrediction dataclass
  model_registry.py          ← ModelRegistry (simile a ProviderRegistry)

tests/engine/forecasting/
  test_base_model.py
  test_probabilistic_prediction.py
  fixtures/
    synthetic_series.py      ← serie AR(1), GBM, stagionale per test
```

**base_model.py:**
```python
# engine/analytics/forecasting/base_model.py
"""BaseModel: interfaccia comune per tutti i modelli di previsione.

Ogni modello (ARIMA, Prophet, RF, XGBoost, LSTM, Ensemble) eredita da BaseModel.
Il ModelRegistry li gestisce e li espone all'ensemble e alle pagine UI.

Regola: ogni modello deve supportare sia predict() (puntuale)
        che predict_probabilistic() (quantili). Se non implementato,
        predict_probabilistic() usa bootstrap come fallback.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import numpy as np
import pandas as pd

@dataclass
class ModelMetrics:
    """Metriche di performance su validation set."""
    mae: float
    rmse: float
    mape: float
    directional_accuracy: float
    validation_start: str
    validation_end: str

class BaseModel(ABC):
    """Interfaccia comune per tutti i modelli di previsione."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Identificatore univoco (es. 'arima', 'xgboost', 'ensemble_weighted')."""
        ...

    @abstractmethod
    def fit(self, train: pd.DataFrame, target_col: str = "Close") -> "BaseModel":
        """Addestra il modello su dati storici. Ritorna self per chaining."""
        ...

    @abstractmethod
    def predict(self, horizon: int) -> pd.Series:
        """
        Previsione puntuale (mediana).
        Args:
            horizon: numero di periodi futuri da prevedere.
        Returns:
            pd.Series con DatetimeIndex (periodi futuri) e valori previsionali.
        """
        ...

    def predict_probabilistic(self, horizon: int) -> "ProbabilisticPrediction":
        """
        Previsione probabilistica con quantili Q10..Q90.
        Default: bootstrap su predict() se il modello non supporta quantili nativi.
        Override in XGBoostModel, EnsemblePredictor.
        """
        point_forecast = self.predict(horizon)
        # Fallback semplice: ±10% come banda di incertezza
        return ProbabilisticPrediction.from_point_forecast(
            point_forecast, uncertainty_pct=0.10
        )

    def get_metrics(self, validation: pd.DataFrame) -> ModelMetrics:
        """Calcola metriche su validation set. Usato da EnsemblePredictor per i pesi."""
        predictions = self.predict(len(validation))
        actual = validation["Close"].values
        pred = predictions.values[:len(actual)]
        mae = float(np.mean(np.abs(actual - pred)))
        rmse = float(np.sqrt(np.mean((actual - pred) ** 2)))
        mape = float(np.mean(np.abs((actual - pred) / (actual + 1e-8))) * 100)
        da = float(np.mean(np.sign(np.diff(actual)) == np.sign(np.diff(pred))))
        return ModelMetrics(mae=mae, rmse=rmse, mape=mape,
                           directional_accuracy=da,
                           validation_start=str(validation.index[0]),
                           validation_end=str(validation.index[-1]))
```

**probabilistic_prediction.py:**
```python
# engine/analytics/forecasting/probabilistic_prediction.py
"""ProbabilisticPrediction: formato unificato per previsioni con quantili.

Usato da tutti i modelli che supportano incertezza:
- XGBoostModel (quantile regression nativa)
- EnsemblePredictor (combinazione distribuzioni)
- ARIMAModel (intervalli di confidenza → conversione)
- ProphetModel (già produce intervalli → conversione)

Il fan chart in Q1_Backtesting.py usa sempre questo formato.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd

@dataclass
class ProbabilisticPrediction:
    """Previsione probabilistica completa con quantili."""
    dates: pd.DatetimeIndex       # periodi previsionali
    q10: np.ndarray               # percentile 10 (pessimistico)
    q25: np.ndarray               # percentile 25
    q50: np.ndarray               # percentile 50 (mediana = previsione centrale)
    q75: np.ndarray               # percentile 75
    q90: np.ndarray               # percentile 90 (ottimistico)
    model_name: str
    target_col: str = "Close"

    def __post_init__(self) -> None:
        assert len(self.dates) == len(self.q50), "dates e q50 devono avere la stessa lunghezza"
        assert (self.q10 <= self.q50).all(), "q10 deve essere ≤ q50"
        assert (self.q50 <= self.q90).all(), "q50 deve essere ≤ q90"

    @classmethod
    def from_point_forecast(
        cls,
        forecast: pd.Series,
        uncertainty_pct: float = 0.10,
        model_name: str = "unknown"
    ) -> "ProbabilisticPrediction":
        """
        Crea una ProbabilisticPrediction da una previsione puntuale
        con banda di incertezza simmetrica (fallback per modelli senza quantili nativi).
        """
        values = forecast.values
        return cls(
            dates=forecast.index,
            q10=values * (1 - uncertainty_pct * 2),
            q25=values * (1 - uncertainty_pct),
            q50=values,
            q75=values * (1 + uncertainty_pct),
            q90=values * (1 + uncertainty_pct * 2),
            model_name=model_name,
        )

    def to_dataframe(self) -> pd.DataFrame:
        """Converti in DataFrame per export o plotting."""
        return pd.DataFrame({
            "date": self.dates,
            "q10": self.q10,
            "q25": self.q25,
            "q50": self.q50,
            "q75": self.q75,
            "q90": self.q90,
            "model": self.model_name,
        }).set_index("date")
```

**Definition of Done — Sessione 1:**
```
□ BaseModel ABC: fit(), predict(), predict_probabilistic(), get_metrics()
□ ProbabilisticPrediction: validazione __post_init__ funzionante
□ ProbabilisticPrediction.from_point_forecast(): fallback simmetrico corretto
□ ModelRegistry: registrazione e listing modelli
□ tests/engine/forecasting/: 100% coverage su base_model.py e probabilistic_prediction.py
□ pytest -m regression: 0 failed
□ mypy --strict: 0 errors sui nuovi file
```

---

## 📅 SESSIONE 2 — XGBoost con Quantile Regression (1–2h)

**Obiettivo:** Aggiornare XGBoostModel per ereditare da BaseModel e supportare quantili nativi

**NON toccare:** altri modelli, interfacce esistenti delle pagine UI

**File da modificare/creare:**
```
models/ml/
  xgboost_model.py         ← aggiornare per ereditare da BaseModel (MODIFICA)
  random_forest_model.py   ← aggiornare per ereditare da BaseModel (MODIFICA)

tests/engine/forecasting/
  test_xgboost_quantile.py ← NUOVO: test quantile regression
  test_rf_quantile.py      ← NUOVO
```

**XGBoostModel — modifiche chiave:**
```python
# models/ml/xgboost_model.py (sezione da aggiungere)

class XGBoostModel(BaseModel):
    """XGBoost con supporto quantile regression nativa."""

    QUANTILES = [0.10, 0.25, 0.50, 0.75, 0.90]

    def fit(self, train: pd.DataFrame, target_col: str = "Close") -> "XGBoostModel":
        # Addestra UN modello per quantile
        self._quantile_models: dict[float, xgb.XGBRegressor] = {}
        X, y = self._build_features(train, target_col)
        for q in self.QUANTILES:
            model = xgb.XGBRegressor(
                objective="reg:quantileerror",
                quantile_alpha=q,
                n_estimators=200,
                max_depth=6,
                learning_rate=0.05,
                tree_method="hist",  # CPU-friendly, non usa GPU
                random_state=42,
            )
            model.fit(X, y)
            self._quantile_models[q] = model
        return self

    def predict_probabilistic(self, horizon: int) -> ProbabilisticPrediction:
        # Predice con ogni modello quantile
        predictions = {}
        for q in self.QUANTILES:
            X_future = self._build_future_features(horizon)
            predictions[q] = self._quantile_models[q].predict(X_future)

        return ProbabilisticPrediction(
            dates=self._future_dates(horizon),
            q10=predictions[0.10],
            q25=predictions[0.25],
            q50=predictions[0.50],
            q75=predictions[0.75],
            q90=predictions[0.90],
            model_name=self.name,
        )
```

**Nota hardware:** `tree_method="hist"` su CPU → non usa GPU (ROCm instabile su Windows). Se in futuro ROCm stabile: cambiare in `tree_method="gpu_hist"` via feature flag.

**Definition of Done — Sessione 2:**
```
□ XGBoostModel eredita da BaseModel: interfaccia completa
□ predict_probabilistic(): 5 quantili corretti (verificati su dati sintetici noti)
□ RandomForestModel eredita da BaseModel con quantile prediction
□ test_xgboost_quantile.py: monotonia quantili verificata (q10 ≤ q25 ≤ q50 ≤ q75 ≤ q90)
□ Nessuna regressione sulle pagine UI che usano XGBoost
□ pytest -m regression: 0 failed
□ tree_method="hist" (CPU) — nessun uso GPU hardcoded
```

---

## 📅 SESSIONE 3 — EnsemblePredictor con 3 Strategie (1–2h)

**Obiettivo:** Creare il livello di combinazione multi-modello

**NON toccare:** modelli base, pagine UI esistenti

**File da creare:**
```
engine/analytics/forecasting/
  ensemble_predictor.py        ← EnsemblePredictor

tests/engine/forecasting/
  test_ensemble_predictor.py   ← test tutte e 3 le strategie
```

**ensemble_predictor.py:**
```python
# engine/analytics/forecasting/ensemble_predictor.py
"""EnsemblePredictor: combina le previsioni di più modelli BaseModel.

Tre strategie selezionabili:
  SIMPLE_AVERAGE  → media aritmetica delle previsioni puntuali
  WEIGHTED        → pesi proporzionali a 1/MAE su validation window recente
  STACKING        → meta-modello Ridge addestrato su out-of-time validation

Utilizzo:
    ensemble = EnsemblePredictor(
        models=[arima, xgboost, prophet],
        strategy="weighted",
        validation_window_days=90,
    )
    ensemble.fit(train_df)
    pred = ensemble.predict_probabilistic(horizon=30)
"""
from __future__ import annotations
from enum import Enum
from typing import Literal
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from engine.analytics.forecasting.base_model import BaseModel
from engine.analytics.forecasting.probabilistic_prediction import ProbabilisticPrediction

EnsembleStrategy = Literal["simple_average", "weighted", "stacking"]

class EnsemblePredictor(BaseModel):

    def __init__(
        self,
        models: list[BaseModel],
        strategy: EnsembleStrategy = "weighted",
        validation_window_days: int = 90,
    ) -> None:
        if len(models) < 2:
            raise ValueError("EnsemblePredictor richiede almeno 2 modelli")
        self._models = models
        self._strategy = strategy
        self._validation_window = validation_window_days
        self._weights: np.ndarray | None = None
        self._meta_model: Ridge | None = None

    @property
    def name(self) -> str:
        return f"ensemble_{self._strategy}"

    def fit(self, train: pd.DataFrame, target_col: str = "Close") -> "EnsemblePredictor":
        # Split train / validation
        val_size = min(self._validation_window, len(train) // 5)
        train_part = train.iloc[:-val_size]
        val_part = train.iloc[-val_size:]

        for model in self._models:
            model.fit(train_part, target_col)

        if self._strategy == "weighted":
            self._compute_weights(val_part)
        elif self._strategy == "stacking":
            self._fit_meta_model(val_part, target_col)

        return self

    def _compute_weights(self, validation: pd.DataFrame) -> None:
        """Pesi = 1/MAE normalizzati (modello più preciso → peso maggiore)."""
        maes = []
        for model in self._models:
            metrics = model.get_metrics(validation)
            maes.append(metrics.mae + 1e-8)  # evita divisione per zero
        inv_maes = np.array([1.0 / m for m in maes])
        self._weights = inv_maes / inv_maes.sum()

    def _fit_meta_model(self, validation: pd.DataFrame, target_col: str) -> None:
        """Stacking: Ridge regression su output dei modelli base."""
        horizon = len(validation)
        X_val = np.column_stack([
            m.predict(horizon).values[:horizon] for m in self._models
        ])
        y_val = validation[target_col].values[:horizon]
        self._meta_model = Ridge(alpha=1.0)
        self._meta_model.fit(X_val, y_val)

    def predict(self, horizon: int) -> pd.Series:
        predictions = [m.predict(horizon) for m in self._models]
        if self._strategy == "simple_average":
            combined = np.mean([p.values for p in predictions], axis=0)
        elif self._strategy == "weighted" and self._weights is not None:
            combined = sum(w * p.values for w, p in zip(self._weights, predictions))
        elif self._strategy == "stacking" and self._meta_model is not None:
            X = np.column_stack([p.values for p in predictions])
            combined = self._meta_model.predict(X)
        else:
            combined = np.mean([p.values for p in predictions], axis=0)
        return pd.Series(combined, index=predictions[0].index)

    def predict_probabilistic(self, horizon: int) -> ProbabilisticPrediction:
        """Combina le distribuzioni probabilistiche dei modelli base."""
        prob_preds = [m.predict_probabilistic(horizon) for m in self._models]
        if self._strategy == "weighted" and self._weights is not None:
            q50 = sum(w * p.q50 for w, p in zip(self._weights, prob_preds))
            q10 = sum(w * p.q10 for w, p in zip(self._weights, prob_preds))
            q90 = sum(w * p.q90 for w, p in zip(self._weights, prob_preds))
        else:
            q50 = np.mean([p.q50 for p in prob_preds], axis=0)
            q10 = np.min([p.q10 for p in prob_preds], axis=0)
            q90 = np.max([p.q90 for p in prob_preds], axis=0)
        return ProbabilisticPrediction(
            dates=prob_preds[0].dates,
            q10=q10,
            q25=np.mean([p.q25 for p in prob_preds], axis=0),
            q50=q50,
            q75=np.mean([p.q75 for p in prob_preds], axis=0),
            q90=q90,
            model_name=self.name,
        )
```

**Definition of Done — Sessione 3:**
```
□ EnsemblePredictor: tutte e 3 le strategie funzionanti
□ Pesi "weighted": più precisione → peso maggiore (verificato con test)
□ Stacking: Ridge meta-model addestrato su out-of-time validation
□ predict_probabilistic(): quantili monotoni (q10 ≤ q25 ≤ q50 ≤ q75 ≤ q90)
□ test_ensemble_predictor.py: almeno 8 test, scenari errore inclusi
□ Ensemble appare nel ModelRegistry come modello selezionabile
□ pytest -m regression: 0 failed
```

---

## 📅 SESSIONE 4 — FeatureBuilder Automatizzato (1–2h)

**Obiettivo:** Creare la pipeline di feature engineering modulare e configurabile

**NON toccare:** modelli esistenti, pipeline di addestramento attuale

**File da creare:**
```
engine/analytics/features/
  __init__.py
  feature_builder.py        ← FeatureBuilder con flag auto_features
  lag_features.py           ← lag, differenze, rendimenti
  rolling_features.py       ← rolling mean/std/min/max, Bollinger
  fourier_features.py       ← componenti Fourier per stagionalità
  selection.py              ← selezione feature per importanza

tests/engine/features/
  test_feature_builder.py
  test_lag_features.py
  test_fourier_features.py
  test_selection.py
```

**feature_builder.py:**
```python
# engine/analytics/features/feature_builder.py
"""FeatureBuilder: pipeline feature engineering modulare.

Uso con feature automatiche (flag=True):
    builder = FeatureBuilder(auto_features=True, max_features=50)
    X = builder.fit_transform(df, target_col="Close")

Uso manuale (retrocompatibile con codice esistente):
    builder = FeatureBuilder(auto_features=False)
    builder.add_lags([1, 5, 10, 20])
    builder.add_rolling(windows=[10, 30])
    X = builder.fit_transform(df)

REGOLA: l'input DataFrame non viene mai modificato.
        Sempre ritornare una copia.
REGOLA: nessun loop Python su serie storiche → numpy vettorizzato.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

@dataclass
class FeatureBuilderConfig:
    auto_features: bool = False
    max_features: int = 50
    lag_periods: list[int] = field(default_factory=lambda: [1, 5, 10, 20])
    rolling_windows: list[int] = field(default_factory=lambda: [10, 30, 60])
    fourier_periods: list[int] = field(default_factory=lambda: [5, 21, 63])
    n_fourier_harmonics: int = 3
    selection_threshold: float = 0.01   # importanza minima per mantenere feature

class FeatureBuilder:
    """Pipeline feature engineering retrocompatibile con feature set attuale."""

    def __init__(
        self,
        auto_features: bool = False,
        max_features: int = 50,
        config: FeatureBuilderConfig | None = None,
    ) -> None:
        self._config = config or FeatureBuilderConfig(
            auto_features=auto_features,
            max_features=max_features,
        )
        self._selected_features: list[str] = []
        self._fitted = False

    def fit_transform(self, df: pd.DataFrame, target_col: str = "Close") -> pd.DataFrame:
        """
        Genera feature e seleziona le più importanti.
        Non modifica df in input. Ritorna copia con feature aggiuntive.
        """
        result = df.copy()
        result = self._add_lag_features(result, target_col)
        result = self._add_rolling_features(result, target_col)
        result = self._add_fourier_features(result)
        result = result.dropna()

        if self._config.auto_features:
            result = self._select_features(result, target_col)

        self._fitted = True
        self._selected_features = [c for c in result.columns if c != target_col]
        return result

    def _add_lag_features(self, df: pd.DataFrame, target_col: str) -> pd.DataFrame:
        """Lag, rendimenti logaritmici, differenze prime — tutto vettorizzato."""
        for lag in self._config.lag_periods:
            df[f"lag_{lag}"] = df[target_col].shift(lag)
            df[f"return_{lag}d"] = np.log(df[target_col] / df[target_col].shift(lag))
        return df

    def _add_rolling_features(self, df: pd.DataFrame, target_col: str) -> pd.DataFrame:
        """Rolling statistics — numpy rolling vettorizzato."""
        for w in self._config.rolling_windows:
            roll = df[target_col].rolling(w)
            df[f"roll_mean_{w}"] = roll.mean()
            df[f"roll_std_{w}"] = roll.std()
            df[f"roll_zscore_{w}"] = (df[target_col] - roll.mean()) / (roll.std() + 1e-8)
        return df

    def _add_fourier_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Componenti di Fourier per catturare stagionalità multipla."""
        t = np.arange(len(df))
        for period in self._config.fourier_periods:
            for h in range(1, self._config.n_fourier_harmonics + 1):
                df[f"fourier_sin_{period}_{h}"] = np.sin(2 * np.pi * h * t / period)
                df[f"fourier_cos_{period}_{h}"] = np.cos(2 * np.pi * h * t / period)
        return df

    def _select_features(self, df: pd.DataFrame, target_col: str) -> pd.DataFrame:
        """Selezione feature tramite correlazione con target (fast proxy)."""
        feature_cols = [c for c in df.columns if c != target_col]
        correlations = df[feature_cols].corrwith(df[target_col]).abs()
        selected = correlations[correlations >= self._config.selection_threshold]
        selected = selected.nlargest(self._config.max_features).index.tolist()
        return df[[target_col] + selected]
```

**Definition of Done — Sessione 4:**
```
□ FeatureBuilder.fit_transform(): retrocompatibile con auto_features=False
□ Lag features: tutto numpy, zero loop Python
□ Fourier features: stagionalità 5gg (settimanale), 21gg (mensile), 63gg (trimestrale)
□ Selezione feature: risultato ≤ max_features
□ Input DataFrame mai modificato (test che verifica immutabilità)
□ test_feature_builder.py: almeno 10 test
□ FeatureBuilder integrato come step opzionale in pipeline addestramento XGBoost
□ pytest -m regression: 0 failed
```

---

## 📅 SESSIONE 5 — Integrazione Dashboard Q1 con Fan Chart (1–2h)

**Obiettivo:** Aggiornare Q1_Backtesting per mostrare bande di incertezza e selettore ensemble

**NON toccare:** logica di calcolo modelli, altri file UI

**File da modificare:**
```
presentation/dashboard_engine/pages/Q1_Backtesting.py    ← aggiungere fan chart
presentation/dashboard_engine/pages/Q2_Stress_Test.py    ← aggiungere ensemble option
```

**Modifiche Q1_Backtesting.py:**
```python
# Aggiungere sezione "Previsione Probabilistica" DOPO la sezione equity curve

# Selettore modello / ensemble
model_choice = st.selectbox(
    "Modello previsione",
    options=ModelRegistry.list_names(),
    index=0,
)

if st.button("📊 Genera previsione probabilistica", key="q1_prob_btn"):
    model = ModelRegistry.get(model_choice)
    model.fit(df_train)
    prob = model.predict_probabilistic(horizon=st.session_state.get("horizon", 30))
    prob_df = prob.to_dataframe()

    # Fan chart Plotly
    fig = go.Figure()
    fig.add_traces([
        go.Scatter(x=prob_df.index, y=prob_df["q90"], name="Q90",
                   line=dict(color="rgba(99,110,250,0.3)"), showlegend=False),
        go.Scatter(x=prob_df.index, y=prob_df["q10"], name="Q10",
                   fill="tonexty", fillcolor="rgba(99,110,250,0.15)",
                   line=dict(color="rgba(99,110,250,0.3)"), showlegend=False),
        go.Scatter(x=prob_df.index, y=prob_df["q50"], name="Mediana",
                   line=dict(color="rgb(99,110,250)", width=2)),
    ])
    fig.update_layout(title=f"Previsione {model_choice} — {horizon} giorni")
    st.plotly_chart(fig, use_container_width=True)
```

**Definition of Done — Sessione 5:**
```
□ Fan chart visibile in Q1 con bande Q10-Q90
□ Selettore modello: include ensemble_weighted e ensemble_stacking
□ Nessun valore hardcoded in UI (tutti da DESIGN_TOKENS o OP_CONFIG)
□ Pagina Q1 carica senza eccezioni con fixture dati test
□ pytest -m regression: 0 failed (pragma: no cover su pagina UI)
```

---

## 📅 SESSIONE 6 — Test Sintetici, Copertura e Validazione Finale (1–2h)

**Obiettivo:** Validare tutto con dati sintetici a proprietà note, aggiornare CLAUDE.md

**File da creare/modificare:**
```
tests/engine/forecasting/
  test_synthetic_series.py    ← NUOVO: AR(1), GBM, stagionale

tests/property_based/
  test_feature_builder_props.py ← Hypothesis: proprietà matematiche FeatureBuilder
```

**test_synthetic_series.py:**
```python
def test_xgboost_captures_trend():
    """XGBoost deve prevedere tendenza corretta su serie con trend lineare noto."""
    dates = pd.date_range("2020-01-01", periods=500, freq="D")
    # Serie con trend perfettamente lineare + rumore piccolo
    trend = np.arange(500) * 0.5 + 100.0
    noise = np.random.normal(0, 0.5, 500)
    df = pd.DataFrame({"Close": trend + noise}, index=dates)

    model = XGBoostModel()
    model.fit(df.iloc[:400])
    pred = model.predict(horizon=30)
    actual = df["Close"].iloc[400:430].values

    # Trend deve essere catturato: direzione corretta
    assert np.corrcoef(pred.values, actual)[0, 1] > 0.8

def test_ensemble_weighted_beats_worst_model():
    """L'ensemble pesato deve performare meglio del modello peggiore."""
    # ... setup con serie sintetica
    # Verifica che MSE ensemble < MSE del modello peggiore
```

**Checklist validazione manuale:**
```
ENSEMBLE:
□ EnsemblePredictor con ARIMA + XGBoost → predict_probabilistic() senza errori
□ Pesi "weighted": il modello più preciso ha peso > 0.4
□ Stacking: Ridge coefficienti sommano a ~1.0

FEATURE ENGINEERING:
□ FeatureBuilder(auto_features=True).fit_transform(df) → ≤50 feature
□ Nessun NaN nel risultato (dopo dropna interna)
□ Input df non modificato (confronto pre/post con df.equals())

FAN CHART:
□ Q1_Backtesting: fan chart visibile in browser
□ Banda Q10-Q90 sempre più larga con horizon crescente

PERFORMANCE (hardware Ryzen 5 5600):
□ FeatureBuilder 10 anni dati giornalieri: < 2s
□ XGBoost 5 quantili 10 anni: < 30s
□ EnsemblePredictor (3 modelli) fit: < 60s
```

**Definition of Done — Sessione 6 (= Definition of Done Fase 2):**
```
□ test_synthetic_series.py: tutti i test passano su serie AR(1) e GBM
□ Hypothesis: proprietà matematiche FeatureBuilder verificate
□ Coverage engine/analytics/forecasting/: ≥ 95%
□ Coverage engine/analytics/features/: 100%
□ mypy --strict su tutti i nuovi file: 0 errors
□ ruff check .: 0 warnings
□ pytest --cov --cov-fail-under=89: verde
□ CLAUDE.md: aggiornato con sezione EnsemblePredictor e FeatureBuilder
□ config/feature_flags.yaml: ensemble_predictor, auto_feature_engineering (default: false)
□ Nessuna regressione su pagine UI esistenti
```

---

## 📁 Struttura File Finale v13.0.0

```
%APPDATA%\MarketAI\
├── engine/
│   └── analytics/
│       ├── forecasting/           ★ NUOVO
│       │   ├── base_model.py
│       │   ├── probabilistic_prediction.py
│       │   ├── model_registry.py
│       │   └── ensemble_predictor.py
│       └── features/              ★ NUOVO
│           ├── feature_builder.py
│           ├── lag_features.py
│           ├── rolling_features.py
│           ├── fourier_features.py
│           └── selection.py
├── models/
│   └── ml/
│       ├── xgboost_model.py       ★ MODIFICATO (eredita BaseModel, quantili)
│       └── random_forest_model.py ★ MODIFICATO (eredita BaseModel, quantili)
├── presentation/
│   └── dashboard_engine/pages/
│       └── Q1_Backtesting.py      ★ MODIFICATO (fan chart + ensemble selector)
├── tests/
│   ├── engine/
│   │   ├── forecasting/           ★ NUOVO
│   │   └── features/              ★ NUOVO
│   └── property_based/
│       └── test_feature_builder_props.py ★ NUOVO
└── config/
    └── feature_flags.yaml         ★ MODIFICATO (nuovi flag)
```

---

## 📊 Metriche di Successo v13.0.0

| Metrica | Target | Note hardware |
|---------|--------|---------------|
| Coverage forecasting/ | ≥ 95% | — |
| Coverage features/ | 100% | — |
| XGBoost 5 quantili fit (10 anni) | < 30s | CPU (tree_method=hist) |
| FeatureBuilder 10 anni daily | < 2s | Ryzen 5 5600 numpy |
| Ensemble fit (3 modelli) | < 60s | CPU, no GPU |
| Quantili monotoni (q10≤q50≤q90) | 100% dataset | Assert in __post_init__ |
| Ensemble vs worst model | MAE ensemble < MAE worst | Verificato su 5 serie sintetiche |
| Fan chart rendering | < 1s | Plotly lato browser |

---

*MarketAI v13.0.0 · Roadmap Fase 2 — Modellistica Avanzata*  
*Pianificazione: Claude Sonnet 4.6 · Implementazione: Claude Code Pro (Opus 4.8)*  
*Prerequisito: v12.0.0 completato · Hardware: Ryzen 5 5600 · RX 6700 8GB · 16GB RAM*
