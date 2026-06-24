# 🟠 ROADMAP — MarketAI v14.0.0 · Fase 3: Modelli Avanzati e Backtesting Realistico
> **v13.0.0 → v14.0.0** · N-BEATS · Backtesting con Costi · Metriche Avanzate · FastAPI  
> Prerequisito: v13.0.0 completato (Ensemble · FeatureBuilder · ProbabilisticPrediction)  
> Pianificazione: Claude Sonnet 4.6 · Implementazione: Claude Code Pro (Opus 4.8)  
> Sessioni: 7 sessioni · Durata stimata: 1–2h ciascuna · Totale: ~5 settimane

---

## 📊 Stato Pre-Fase 3

| Parametro | Valore |
|-----------|--------|
| Versione base | v13.0.0 (Ensemble + FeatureBuilder attivi) |
| Hardware | Ryzen 5 5600 · RX 6700 8GB VRAM · 16GB RAM · 512GB NVMe |
| PyTorch mode | **CPU only** (ROCm su Windows non stabile su RX 6700) |
| Modelli DL | LSTM/GRU/Transformer esistenti — feature flag off di default |
| Gap principali | Nessun DL moderno · Backtesting senza costi · Metriche limitate |

---

## 🎯 Obiettivi v14.0.0

### Obbligatori

```
[OB-1] N-BEATS (Neural Basis Expansion Analysis)
        · Implementazione PyTorch CPU-first
        · Stack decomposizione: trend + stagionalità
        · Feature flag nbeats_model (default: false)
        · Integrazione in BaseModel / ModelRegistry

[OB-2] Backtesting Engine con Costi Realistici
        · Commissioni fisse/percentuali configurabili
        · Slippage basato su volatilità corrente
        · Vincoli di liquidità (volume giornaliero)
        · Equity curve netta e breakdown costi
        · Sostituisce il backtester esistente (retrocompatibile)

[OB-3] Metriche di Valutazione Avanzate
        · SMAPE, Theil's U, MDA con test binomiale
        · Pinball Loss / Quantile Loss per modelli probabilistici
        · CRPS (Continuous Ranked Probability Score)
        · Dashboard diagnostica unificata in Q1_Backtesting

[OB-4] API REST con FastAPI (prima versione)
        · Endpoint: /predict · /backtest · /models · /health
        · Autenticazione API key (header X-API-Key)
        · Swagger UI su /docs
        · Streamlit rimane come client (NON eliminarlo)
```

### Facoltativi (solo se OB-1/2/3/4 completi)

```
[OPT-1] Temporal Fusion Transformer (pytorch-forecasting) — pesante su 16GB RAM
[OPT-2] Benchmarking multi-asset automatizzato (run_benchmark.py)
[OPT-3] Test di White (Reality Check) e Model Confidence Set
```

---

## ⚠️ Vincoli Hardware — CRITICO per Sessioni DL

```
PYTORCH SU CPU (RX 6700 → ROCm instabile su Windows):
  · N-BEATS training su 10 anni daily: ~5-10 minuti su CPU
  · Batch size massimo: 64 (oltre → OOM con 16GB RAM + altri processi)
  · Max hidden_size: 256 per N-BEATS (512 può saturare RAM)
  · Disabilitare torch.compile() → non supportato stabily su CPU Windows
  · Usare torch.set_num_threads(4) → lascia 2 core per OS

STIMA MEMORIA (worst case con tutti i processi attivi):
  · Streamlit dashboard: ~800MB
  · DuckDB 10 anni 100 ticker: ~2GB
  · N-BEATS training (batch 64, hidden 256): ~3GB
  · Sistema operativo + browser: ~4GB
  · TOTALE: ~10GB → margine sicuro su 16GB
  · SE RAM < 2GB libera → feature flag nbeats_model si auto-disabilita

REGOLA ASSOLUTA:
  · nbeats_model: false in feature_flags.yaml (default)
  · L'utente attiva manualmente DOPO aver verificato RAM disponibile
  · Aggiungere check RAM a runtime prima del training DL
```

---

## 🧩 Anti-Pattern Vietati v14.0.0

```
❌ N-BEATS che tenta training senza check RAM disponibile
   → ram_check.py: if available_ram_gb() < 4: raise InsufficientMemoryError

❌ Backtesting con slippage zero o commissioni zero di default
   → Config minimo: fees=0.001, slippage=0.001 (Regola 23)

❌ Metrica predittiva calcolata in-sample
   → SEMPRE su validation/test set out-of-sample

❌ FastAPI che importa direttamente da presentation/
   → Solo da engine/ e shared/ — mai da presentation/

❌ Endpoint FastAPI esposto senza autenticazione
   → X-API-Key header obbligatorio (Regola 32 adattata)

❌ Equity curve calcolata senza sottrarre commissioni e slippage
   → equity_net = equity_gross - total_costs SEMPRE

❌ Modello DL abilitato di default
   → feature_flags.yaml: nbeats_model: false

❌ torch.compile() su Windows/CPU
   → Non supportato stabily → mai usarlo in questo setup

❌ Sessione Opus senza regression test iniziale → 0 failed obbligatorio
```

---

## 📅 SESSIONE 1 — N-BEATS: Implementazione Kernel PyTorch CPU (1–2h)

**Obiettivo:** Creare N-BEATS PyTorch ottimizzato per CPU con 16GB RAM

**NON toccare:** modelli esistenti, LSTM/GRU, pyproject.toml (PyTorch già presente)

**File da creare:**
```
engine/analytics/forecasting/
  nbeats/
    __init__.py
    nbeats_block.py        ← NBeatsBlock (fully connected + basis expansion)
    nbeats_stack.py        ← NBeatsStack (trend + seasonality stacks)
    nbeats_model.py        ← NBeatsModel (eredita BaseModel)
    ram_check.py           ← check RAM disponibile prima del training

tests/engine/forecasting/
  test_nbeats.py
```

**ram_check.py:**
```python
# engine/analytics/forecasting/nbeats/ram_check.py
"""Verifica RAM disponibile prima di avviare training DL pesante.

Usato da NBeatsModel.fit() come guard obbligatorio.
"""
from __future__ import annotations
import os
import structlog
log = structlog.get_logger(__name__)

class InsufficientMemoryError(Exception):
    """RAM disponibile insufficiente per il training richiesto."""

def available_ram_gb() -> float:
    """Ritorna RAM disponibile in GB (cross-platform)."""
    try:
        import psutil
        return psutil.virtual_memory().available / (1024 ** 3)
    except ImportError:
        log.warning("ram_check.psutil_missing")
        return 999.0  # assumi sufficiente se psutil non disponibile

def require_ram(min_gb: float, context: str = "") -> None:
    """
    Verifica RAM disponibile.
    Raises:
        InsufficientMemoryError: se RAM disponibile < min_gb.
    """
    available = available_ram_gb()
    if available < min_gb:
        raise InsufficientMemoryError(
            f"RAM insufficiente per {context}: "
            f"{available:.1f}GB disponibili, {min_gb}GB richiesti. "
            f"Chiudi altre applicazioni o disabilita nbeats_model in feature_flags.yaml"
        )
    log.info("ram_check.ok", available_gb=round(available, 1), required_gb=min_gb)
```

**nbeats_model.py — struttura principale:**
```python
# engine/analytics/forecasting/nbeats/nbeats_model.py
"""N-BEATS: Neural Basis Expansion Analysis for Time Series.

Paper: Oreshkin et al. 2019 (https://arxiv.org/abs/1905.10437)
Implementazione CPU-first, ottimizzata per 16GB RAM.

Configurazione consigliata per Ryzen 5 5600 (CPU):
  hidden_size=128      → ~1.5GB RAM durante training
  hidden_size=256      → ~3GB RAM durante training (MAX CONSIGLIATO)
  stack_types=["trend","seasonality"]
  num_blocks_per_stack=3
  batch_size=32        → sicuro su 16GB
  max_epochs=50        → training ~5-8 min su CPU

Feature flag: nbeats_model deve essere True (config/feature_flags.yaml)
              E RAM disponibile > 4GB (check automatico in fit())
"""
from __future__ import annotations
from typing import Literal
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import structlog

from engine.analytics.forecasting.base_model import BaseModel
from engine.analytics.forecasting.probabilistic_prediction import ProbabilisticPrediction
from engine.analytics.forecasting.nbeats.ram_check import require_ram
from shared.feature_flags import require_enabled

log = structlog.get_logger(__name__)

StackType = Literal["trend", "seasonality", "generic"]

class NBeatsModel(BaseModel):
    """N-BEATS implementato in PyTorch, ottimizzato per CPU."""

    def __init__(
        self,
        lookback_window: int = 60,       # giorni storici in input
        forecast_horizon: int = 30,      # giorni da prevedere
        hidden_size: int = 128,          # 128 sicuro, 256 max consigliato
        num_blocks_per_stack: int = 3,
        stack_types: list[StackType] | None = None,
        batch_size: int = 32,
        max_epochs: int = 50,
        learning_rate: float = 1e-3,
    ) -> None:
        self._lookback = lookback_window
        self._horizon = forecast_horizon
        self._hidden = hidden_size
        self._batch_size = batch_size
        self._max_epochs = max_epochs
        self._lr = learning_rate
        self._stack_types = stack_types or ["trend", "seasonality"]
        self._num_blocks = num_blocks_per_stack
        self._net: nn.Module | None = None
        self._scaler_mean: float = 0.0
        self._scaler_std: float = 1.0

        # CPU-only: mai usare CUDA/ROCm
        self._device = torch.device("cpu")
        torch.set_num_threads(4)  # Ryzen 5 5600: 4 thread sicuri

    @property
    def name(self) -> str:
        return "nbeats"

    def fit(self, train: pd.DataFrame, target_col: str = "Close") -> "NBeatsModel":
        # Guard obbligatori
        require_enabled("nbeats_model")
        require_ram(min_gb=4.0, context="N-BEATS training")

        series = train[target_col].values.astype(np.float32)
        # Normalizzazione z-score
        self._scaler_mean = float(series.mean())
        self._scaler_std = float(series.std()) + 1e-8
        series_norm = (series - self._scaler_mean) / self._scaler_std

        # Costruzione dataset con finestre scorrevoli
        X, y = self._build_windows(series_norm)

        # Costruzione rete
        self._net = self._build_network()
        optimizer = torch.optim.Adam(self._net.parameters(), lr=self._lr)

        X_t = torch.tensor(X, device=self._device)
        y_t = torch.tensor(y, device=self._device)

        log.info("nbeats.training_start", epochs=self._max_epochs, device="cpu")
        self._net.train()
        for epoch in range(self._max_epochs):
            # Mini-batch training
            perm = torch.randperm(len(X_t))
            total_loss = 0.0
            for i in range(0, len(X_t), self._batch_size):
                idx = perm[i:i + self._batch_size]
                pred = self._net(X_t[idx])
                loss = nn.MSELoss()(pred, y_t[idx])
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                total_loss += loss.item()
            if epoch % 10 == 0:
                log.info("nbeats.epoch", epoch=epoch, loss=round(total_loss, 4))

        log.info("nbeats.training_complete")
        return self

    def predict(self, horizon: int) -> pd.Series:
        # ... implementazione ricorsiva multi-step
        raise NotImplementedError("predict() implementato in nbeats_model.py completo")

    def _build_windows(self, series: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Crea finestre scorrevoli per training N-BEATS."""
        X, y = [], []
        for i in range(self._lookback, len(series) - self._horizon + 1):
            X.append(series[i - self._lookback:i])
            y.append(series[i:i + self._horizon])
        return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)

    def _build_network(self) -> nn.Module:
        """Costruisce la rete N-BEATS con stack trend + stagionalità."""
        # Implementazione completa in nbeats_stack.py
        raise NotImplementedError("Implementato in nbeats_stack.py")
```

**Aggiungere a pyproject.toml:**
```toml
psutil = "^5.9"    # per ram_check.py — aggiungere SOLO se non presente
```

**Definition of Done — Sessione 1:**
```
□ ram_check.py: require_ram() funzionante (testato con psutil mock)
□ NBeatsModel: eredita BaseModel, type hints completi
□ fit() blocca se nbeats_model flag è False
□ fit() blocca se RAM < 4GB (testato con mock psutil)
□ torch.set_num_threads(4) — nessun uso CUDA/ROCm
□ test_nbeats.py: training su serie sintetica 500 punti < 60s su CPU
□ pytest -m regression: 0 failed
□ config/feature_flags.yaml: nbeats_model: false (default sicuro)
```

---

## 📅 SESSIONE 2 — N-BEATS: Stack Completo e Integrazione (1–2h)

**Obiettivo:** Completare implementazione N-BEATS e integrare in ModelRegistry

**NON toccare:** altri modelli, pagine UI

**File da completare/creare:**
```
engine/analytics/forecasting/nbeats/
  nbeats_block.py        ← NBeatsBlock implementazione completa
  nbeats_stack.py        ← TrendStack + SeasonalityStack

tests/engine/forecasting/
  test_nbeats_integration.py  ← test integrazione con ModelRegistry
```

**nbeats_block.py — implementazione:**
```python
class NBeatsBlock(nn.Module):
    """Blocco base N-BEATS: FC layers + basis expansion."""

    def __init__(
        self,
        input_size: int,          # lookback window
        output_size: int,         # forecast horizon
        hidden_size: int = 128,
        num_layers: int = 4,
        basis_type: StackType = "generic",
        degree_of_polynomial: int = 3,    # per trend
        num_harmonics: int = 2,           # per stagionalità
    ) -> None:
        super().__init__()
        # Fully connected layers
        layers = [nn.Linear(input_size, hidden_size), nn.ReLU()]
        for _ in range(num_layers - 1):
            layers.extend([nn.Linear(hidden_size, hidden_size), nn.ReLU()])
        self.fc = nn.Sequential(*layers)

        # Proiezione backcast e forecast
        if basis_type == "trend":
            self.theta_size = degree_of_polynomial + 1
        elif basis_type == "seasonality":
            self.theta_size = 2 * num_harmonics
        else:
            self.theta_size = input_size + output_size

        self.theta_b = nn.Linear(hidden_size, self.theta_size, bias=False)
        self.theta_f = nn.Linear(hidden_size, self.theta_size, bias=False)
        self._basis_type = basis_type
        self._input_size = input_size
        self._output_size = output_size
        self._degree = degree_of_polynomial
        self._harmonics = num_harmonics

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        h = self.fc(x)
        theta_b = self.theta_b(h)
        theta_f = self.theta_f(h)
        backcast = self._expand_basis(theta_b, self._input_size)
        forecast = self._expand_basis(theta_f, self._output_size)
        return backcast, forecast

    def _expand_basis(self, theta: torch.Tensor, size: int) -> torch.Tensor:
        if self._basis_type == "trend":
            t = torch.arange(size, dtype=torch.float32) / size
            # Base polinomiale [1, t, t², t³, ...]
            basis = torch.stack([t ** i for i in range(self._degree + 1)], dim=0)
            return theta @ basis
        elif self._basis_type == "seasonality":
            t = torch.arange(size, dtype=torch.float32)
            cos_terms = [torch.cos(2 * torch.pi * h * t / size) for h in range(1, self._harmonics + 1)]
            sin_terms = [torch.sin(2 * torch.pi * h * t / size) for h in range(1, self._harmonics + 1)]
            basis = torch.stack(cos_terms + sin_terms, dim=0)
            return theta @ basis
        else:
            return theta  # generic: theta = output direttamente
```

**Definition of Done — Sessione 2:**
```
□ NBeatsBlock.forward(): backcast + forecast con shape corrette
□ TrendStack: basis espansione polinomiale verificata
□ SeasonalityStack: componenti Fourier verificate
□ NBeatsModel.predict(): previsione 30 giorni su serie sintetica < 10s (CPU)
□ NBeatsModel appare nel ModelRegistry
□ test_nbeats_integration.py: end-to-end fit→predict su dati sintetici
□ pytest -m regression: 0 failed
```

---

## 📅 SESSIONE 3 — Backtesting Engine con Costi Realistici (1–2h)

**Obiettivo:** Sostituire il backtester attuale con simulatore che include commissioni, slippage, liquidità

**NON toccare:** Q1_Backtesting.py UI (solo l'engine), VectorBT (rimane per backtest esistenti)

**File da creare:**
```
engine/analytics/backtesting/
  realistic_backtester.py    ← RealisticBacktester (simulatore a eventi)
  cost_model.py              ← CostModel (commissioni + slippage)
  liquidity_filter.py        ← vincoli volume giornaliero
  backtest_report.py         ← BacktestReport con metriche lorde/nette

tests/engine/backtesting/
  test_realistic_backtester.py
  test_cost_model.py
```

**cost_model.py:**
```python
# engine/analytics/backtesting/cost_model.py
"""CostModel: modellazione commissioni, slippage e market impact.

Configurazione (da config/backtesting.yaml):
  commission_type: "percentage"   # "fixed" o "percentage"
  commission_value: 0.001         # 0.1% per trade (minimo Regola 23)
  slippage_type: "volatility"     # "fixed" o "volatility"
  slippage_pct: 0.001             # 0.1% fisso (se slippage_type="fixed")
  slippage_vol_multiplier: 0.5    # slippage = 0.5 * rolling_std (se "volatility")
  min_commission: 1.0             # commissione minima in EUR/USD

Regola 23: fees ≥ 0.001, slippage ≥ 0.001 SEMPRE.
           Nessun backtest senza costi viene accettato.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
import numpy as np

CommissionType = Literal["fixed", "percentage"]
SlippageType = Literal["fixed", "volatility"]

@dataclass
class CostConfig:
    commission_type: CommissionType = "percentage"
    commission_value: float = 0.001     # 0.1% — MINIMO assoluto (Regola 23)
    slippage_type: SlippageType = "volatility"
    slippage_pct: float = 0.001         # 0.1% fisso
    slippage_vol_multiplier: float = 0.5
    min_commission: float = 1.0         # commissione minima EUR
    max_volume_fraction: float = 0.05   # max 5% volume giornaliero

    def __post_init__(self) -> None:
        # Regola 23: mai sotto i minimi
        if self.commission_value < 0.001:
            raise ValueError("commission_value < 0.001 viola Regola 23")
        if self.commission_type == "fixed" and self.slippage_pct < 0.001:
            raise ValueError("slippage_pct < 0.001 viola Regola 23")

class CostModel:
    """Calcola costi realistici per ogni operazione di trading."""

    def __init__(self, config: CostConfig | None = None) -> None:
        self._cfg = config or CostConfig()

    def commission(self, trade_value: float) -> float:
        """Commissione per una singola operazione (in valuta base)."""
        if self._cfg.commission_type == "percentage":
            return max(trade_value * self._cfg.commission_value, self._cfg.min_commission)
        else:
            return self._cfg.min_commission

    def slippage(self, price: float, volatility: float | None = None) -> float:
        """Slippage in punti prezzo (aggiustamento dell'execution price)."""
        if self._cfg.slippage_type == "fixed":
            return price * self._cfg.slippage_pct
        else:
            vol = volatility or self._cfg.slippage_pct * 2
            return price * (vol * self._cfg.slippage_vol_multiplier)

    def total_trade_cost(
        self, price: float, quantity: float, volatility: float | None = None
    ) -> float:
        """Costo totale (commissione + slippage) per un'operazione."""
        trade_value = abs(price * quantity)
        comm = self.commission(trade_value)
        slip = self.slippage(price, volatility) * abs(quantity)
        return comm + slip
```

**realistic_backtester.py — struttura:**
```python
# engine/analytics/backtesting/realistic_backtester.py
"""RealisticBacktester: simulatore backtesting con costi realistici.

Sostituisce il backtester semplificato con un simulatore a eventi che:
  1. Applica commissioni e slippage ad ogni operazione
  2. Rispetta vincoli di liquidità (volume giornaliero)
  3. Calcola equity curve NETTA (al netto di tutti i costi)
  4. Produce report con breakdown costi

Retrocompatibilità: l'interfaccia è identica a quella del backtester attuale.
VectorBT rimane disponibile per backtest veloci (Regola 23).
"""

@dataclass
class BacktestResult:
    equity_curve_gross: pd.Series   # equity PRIMA dei costi
    equity_curve_net: pd.Series     # equity DOPO tutti i costi
    total_commission: float
    total_slippage: float
    total_cost: float
    sharpe_ratio: float
    sharpe_ratio_net: float         # Sharpe sull'equity netta
    max_drawdown: float
    max_drawdown_net: float
    win_rate: float
    profit_factor: float
    n_trades: int
    avg_trade_duration_days: float
    cost_breakdown: pd.DataFrame    # dettaglio per ogni operazione

class RealisticBacktester:
    """Backtester event-driven con modellazione completa dei costi."""

    def __init__(
        self,
        cost_config: CostConfig | None = None,
        initial_capital: float = 10_000.0,
    ) -> None:
        self._cost_model = CostModel(cost_config)
        self._capital = initial_capital

    def run(
        self,
        prices: pd.Series,           # prezzi storici
        signals: pd.Series,          # +1 long · -1 short · 0 flat
        volume: pd.Series | None = None,
    ) -> BacktestResult:
        """
        Esegue il backtest.
        Signals devono essere shiftati di 1 (Regola 23: anti look-ahead).
        """
        # Verifica shift(1) applicato (i segnali non usano il prezzo corrente)
        # ... implementazione completa
```

**Definition of Done — Sessione 3:**
```
□ CostConfig.__post_init__: blocca se commission < 0.001 (Regola 23)
□ BacktestResult: equity_curve_net sempre ≤ equity_curve_gross
□ test_cost_model.py: commissioni, slippage, liquidità su scenari noti
□ test_realistic_backtester.py: equity netta < lordo su tutti i test
□ BacktestReport: Sharpe netto, MaxDD netto, breakdown costi
□ VectorBT non modificato (rimane per backtest veloci esistenti)
□ pytest -m regression: 0 failed
```

---

## 📅 SESSIONE 4 — Metriche Avanzate e Dashboard Diagnostica (1–2h)

**Obiettivo:** Aggiungere SMAPE, Theil's U, Pinball Loss, CRPS e dashboard comparativa

**NON toccare:** metodo di addestramento modelli, pagine UI esistenti (tranne Q1)

**File da creare:**
```
engine/analytics/evaluation/
  advanced_metrics.py          ← SMAPE, Theil's U, MDA, Pinball, CRPS
  residual_diagnostics.py      ← ACF, ARCH LM, Jarque-Bera, CUSUM
  model_comparison.py          ← tabella comparativa multi-modello

tests/engine/evaluation/
  test_advanced_metrics.py
  test_residual_diagnostics.py
```

**advanced_metrics.py:**
```python
# engine/analytics/evaluation/advanced_metrics.py
"""Metriche di valutazione avanzate per previsioni finanziarie.

Tutte le funzioni accettano array numpy e ritornano float.
Nessuna dipendenza da modelli specifici: libreria riutilizzabile.
"""
from __future__ import annotations
import numpy as np
from scipy import stats

def smape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Symmetric Mean Absolute Percentage Error [0, 200%].
    Simmetrico rispetto a MAPE: tratta over/under prediction ugualmente.
    """
    denominator = (np.abs(actual) + np.abs(predicted)) / 2 + 1e-8
    return float(np.mean(np.abs(actual - predicted) / denominator) * 100)

def theil_u2(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Theil's U2: confronto vs naive forecast (ultimo valore).
    U2 < 1 → modello batte naive · U2 = 1 → pari al naive · U2 > 1 → peggio del naive.
    """
    naive = actual[:-1]           # previsione naive = valore precedente
    actual_h = actual[1:]
    pred_h = predicted[1:]
    mse_model = np.mean((actual_h - pred_h) ** 2)
    mse_naive = np.mean((actual_h - naive) ** 2)
    return float(np.sqrt(mse_model / (mse_naive + 1e-8)))

def mda_with_significance(actual: np.ndarray, predicted: np.ndarray) -> dict:
    """Mean Directional Accuracy con test binomiale per significatività.
    Returns: {'mda': float, 'p_value': float, 'is_significant': bool}
    """
    directions_actual = np.sign(np.diff(actual))
    directions_pred = np.sign(np.diff(predicted))
    correct = (directions_actual == directions_pred).sum()
    total = len(directions_actual)
    mda = correct / total
    # Test binomiale: H0 = MDA = 0.5 (random)
    p_value = stats.binomtest(correct, total, 0.5, alternative="greater").pvalue
    return {"mda": float(mda), "p_value": float(p_value), "is_significant": p_value < 0.05}

def pinball_loss(actual: np.ndarray, predicted_quantile: np.ndarray, q: float) -> float:
    """Pinball (Quantile) Loss per valutare previsioni probabilistiche.
    Args:
        q: quantile target (es. 0.10, 0.50, 0.90)
    Returns:
        loss media (più bassa = meglio)
    """
    errors = actual - predicted_quantile
    loss = np.where(errors >= 0, q * errors, (q - 1) * errors)
    return float(np.mean(loss))

def crps(actual: np.ndarray, q10: np.ndarray, q50: np.ndarray, q90: np.ndarray) -> float:
    """Continuous Ranked Probability Score (approssimato via quantili).
    Misura la qualità di una previsione probabilistica.
    Più basso = meglio.
    """
    # Approssimazione CRPS via pinball loss su Q10, Q50, Q90
    return (
        pinball_loss(actual, q10, 0.10) +
        pinball_loss(actual, q50, 0.50) +
        pinball_loss(actual, q90, 0.90)
    ) / 3

def tail_weighted_loss(actual: np.ndarray, predicted: np.ndarray, tail_pct: float = 0.10) -> float:
    """Media degli errori nel tail peggiore (es. top 10% errori assoluti).
    Utile per valutare la capacità di prevedere eventi estremi.
    """
    abs_errors = np.abs(actual - predicted)
    threshold = np.percentile(abs_errors, (1 - tail_pct) * 100)
    tail_errors = abs_errors[abs_errors >= threshold]
    return float(np.mean(tail_errors))
```

**Definition of Done — Sessione 4:**
```
□ smape(): 0% su serie perfetta, ~200% su errore massimo
□ theil_u2(): < 1 se modello batte naive (verificato su serie note)
□ mda_with_significance(): p_value corretto con scipy.stats.binomtest
□ pinball_loss(): asimmetria corretta (Q10 penalizza underestimate)
□ crps(): sempre ≥ 0, = 0 su previsione perfetta
□ test_advanced_metrics.py: tutti i casi con valori attesi verificati
□ Dashboard Q1: tabella comparativa con SMAPE, Theil's U, MDA, CRPS
□ pytest -m regression: 0 failed
```

---

## 📅 SESSIONE 5 — FastAPI Backend (prima versione) (1–2h)

**Obiettivo:** Creare l'API REST che espone le funzionalità principali di MarketAI

**NON toccare:** Streamlit dashboard (rimane come client)

**File da creare:**
```
api/
  __init__.py
  main.py              ← FastAPI app + middleware + health
  auth.py              ← autenticazione X-API-Key
  routes/
    __init__.py
    predict.py         ← POST /predict
    backtest.py        ← POST /backtest
    models.py          ← GET /models
    health.py          ← GET /health

tests/api/
  test_predict_endpoint.py
  test_backtest_endpoint.py
  test_auth.py
```

**main.py:**
```python
# api/main.py
"""MarketAI REST API — FastAPI backend.

Espone le funzionalità di engine/ come API REST.
NON importa da presentation/ — solo da engine/ e shared/.

Avvio in sviluppo:
    poetry run uvicorn api.main:app --reload --port 8502

Avvio in produzione (Management UI):
    poetry run uvicorn api.main:app --host 127.0.0.1 --port 8502 --workers 2

Autenticazione: X-API-Key header (valore da .env: MARKETAI_API_KEY)
Docs: http://localhost:8502/docs (Swagger UI)
"""
from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import predict, backtest, models, health
from api.auth import APIKeyMiddleware
from shared.logging_config import setup_logging

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    yield

app = FastAPI(
    title="MarketAI API",
    version="14.0.0",
    description="REST API per analisi mercati finanziari",
    docs_url="/docs",
    lifespan=lifespan,
)

app.add_middleware(APIKeyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],  # solo Streamlit locale
    allow_methods=["GET", "POST"],
    allow_headers=["X-API-Key"],
)

app.include_router(health.router, tags=["System"])
app.include_router(models.router, prefix="/models", tags=["Models"])
app.include_router(predict.router, prefix="/predict", tags=["Forecasting"])
app.include_router(backtest.router, prefix="/backtest", tags=["Backtesting"])
```

**routes/predict.py:**
```python
from pydantic import BaseModel, Field

class PredictRequest(BaseModel):
    symbol: str = Field(..., example="AAPL")
    horizon_days: int = Field(30, ge=1, le=252)
    model_name: str = Field("xgboost", example="xgboost")
    start_date: str = Field("2020-01-01")
    probabilistic: bool = Field(True)

class PredictResponse(BaseModel):
    symbol: str
    model_name: str
    dates: list[str]
    q50: list[float]                 # mediana
    q10: list[float] | None = None   # solo se probabilistic=True
    q90: list[float] | None = None
    metrics: dict | None = None

@router.post("/", response_model=PredictResponse)
async def predict_endpoint(req: PredictRequest):
    """Previsione puntuale o probabilistica per un simbolo."""
    # 1. Fetch dati tramite ProviderRegistry
    # 2. Addestra modello richiesto
    # 3. Genera ProbabilisticPrediction
    # 4. Ritorna PredictResponse
    ...
```

**Aggiungere a pyproject.toml (Sessione 5 — unica modifica consentita):**
```toml
fastapi = "^0.111"
uvicorn = {extras = ["standard"], version = "^0.30"}
httpx = "^0.27"    # per test API con pytest
```

**Definition of Done — Sessione 5:**
```
□ GET /health: ritorna {"status": "operational"} senza autenticazione
□ GET /models: lista modelli disponibili con feature flags rispettati
□ POST /predict: previsione XGBoost con ProbabilisticPrediction → 200 OK
□ POST /backtest: run backtest con costi → BacktestResult → 200 OK
□ Richiesta senza X-API-Key → 401 Unauthorized
□ Swagger UI su /docs funzionante
□ test_auth.py: no key → 401, chiave errata → 401, chiave corretta → 200
□ MARKETAI_API_KEY aggiunto a .env.example
□ pytest -m regression: 0 failed
□ NON importa da presentation/
```

---

## 📅 SESSIONE 6 — Diagnostica Residui e Report Automatico (1–2h)

**Obiettivo:** Aggiungere analisi diagnostica residui e report semaforico

**NON toccare:** modelli, FastAPI già creato

**File da creare:**
```
engine/analytics/evaluation/
  residual_diagnostics.py      ← test statistici residui
  diagnostic_report.py         ← report semaforico automatico
```

**residual_diagnostics.py:**
```python
def ljung_box_test(residuals: np.ndarray, lags: int = 10) -> dict:
    """Test Ljung-Box per autocorrelazione residui.
    Returns: {'statistic': float, 'p_value': float, 'is_autocorrelated': bool}
    p_value < 0.05 → residui autocorrelati → modello mal specificato.
    """
    from statsmodels.stats.diagnostic import acorr_ljungbox
    result = acorr_ljungbox(residuals, lags=[lags], return_df=True)
    p_val = float(result["lb_pvalue"].iloc[0])
    return {"statistic": float(result["lb_stat"].iloc[0]),
            "p_value": p_val, "is_autocorrelated": p_val < 0.05}

def arch_lm_test(residuals: np.ndarray, lags: int = 5) -> dict:
    """Test ARCH LM per eteroschedasticità condizionale.
    Rileva volatility clustering non modellato.
    """
    from statsmodels.stats.diagnostic import het_arch
    stat, p_val, _, _ = het_arch(residuals, nlags=lags)
    return {"statistic": float(stat), "p_value": float(p_val),
            "has_arch_effect": p_val < 0.05}

def jarque_bera_test(residuals: np.ndarray) -> dict:
    """Test Jarque-Bera per normalità residui."""
    stat, p_val = stats.jarque_bera(residuals)
    return {"statistic": float(stat), "p_value": float(p_val),
            "is_normal": p_val >= 0.05}

def generate_diagnostic_report(
    actual: np.ndarray,
    predicted: np.ndarray,
    model_name: str,
) -> dict:
    """
    Report diagnostico completo con semaforo:
      VERDE  → tutti i test OK
      GIALLO → 1-2 problemi minori
      ROSSO  → problemi gravi (autocorrelazione + ARCH insieme)
    """
    residuals = actual - predicted
    lb = ljung_box_test(residuals)
    arch = arch_lm_test(residuals)
    jb = jarque_bera_test(residuals)

    issues = []
    if lb["is_autocorrelated"]:
        issues.append("AUTOCORRELAZIONE: considera aggiungere più lag")
    if arch["has_arch_effect"]:
        issues.append("ARCH EFFECT: volatilità non modellata correttamente")
    if not jb["is_normal"]:
        issues.append("NON NORMALITÀ: distribuzioni con code pesanti")

    if len(issues) == 0:
        status = "VERDE"
    elif len(issues) <= 1:
        status = "GIALLO"
    else:
        status = "ROSSO"

    return {
        "model": model_name,
        "status": status,
        "issues": issues,
        "tests": {"ljung_box": lb, "arch_lm": arch, "jarque_bera": jb},
    }
```

**Definition of Done — Sessione 6:**
```
□ ljung_box_test(): p_value corretto (verificato su serie AR(1) nota)
□ arch_lm_test(): rilevamento ARCH su serie GARCH(1,1) sintetica
□ generate_diagnostic_report(): semaforo corretto su 3 scenari test
□ Report visualizzato in Q1_Backtesting sidebar
□ test_residual_diagnostics.py: tutti i test con valori attesi noti
□ pytest -m regression: 0 failed
```

---

## 📅 SESSIONE 7 — Integrazione Finale, CLAUDE.md e Validazione (1–2h)

**Obiettivo:** Connettere tutti i pezzi, aggiornare CLAUDE.md, validazione hardware reale

**Attività:**
```
1. Integrare RealisticBacktester in Q1_Backtesting.py:
   · Selettore "Backtest semplice (VectorBT)" vs "Backtest realistico"
   · Mostrare breakdown costi accanto all'equity curve

2. Aggiornare CLAUDE.md sezione "Moduli Chiave":
   · NBeatsModel (con nota RAM e feature flag)
   · RealisticBacktester (con nota costi minimi Regola 23)
   · FastAPI endpoints (URL, autenticazione)
   · advanced_metrics (SMAPE, Theil's U, Pinball, CRPS)
   · residual_diagnostics (semaforo)

3. Aggiornare config/feature_flags.yaml:
   nbeats_model: false         # attivare solo con RAM > 6GB libera
   realistic_backtester: true  # default on (retrocompatibile)
   fastapi_backend: false      # utente avvia manualmente

4. Validazione manuale su hardware reale:
   · N-BEATS fit 500 punti CPU → tempo misurato
   · RealisticBacktester su 10 anni AAPL → equity netta < lordo verificata
   · FastAPI /predict con Postman o curl
```

**Checklist validazione hardware Ryzen 5 5600:**
```
N-BEATS (feature flag: true, hidden_size=128):
□ require_ram(4.0): passa con 16GB (solo sistema + MarketAI)
□ fit() su 2 anni daily (500 punti): < 3 minuti CPU
□ predict(30): < 5 secondi
□ Memoria usata: < 3GB (verificata con Task Manager)

REALISTIC BACKTESTER:
□ AAPL 10 anni: equity_net < equity_gross (commissioni 0.1%)
□ total_cost breakdown: commissioni + slippage somma corretta
□ Sharpe netto < Sharpe lordo

FASTAPI:
□ uvicorn avvio: < 5 secondi
□ GET /health: 200 OK < 50ms
□ POST /predict (XGBoost 1 anno): 200 OK < 10 secondi
□ Swagger /docs: interfaccia navigabile
```

**Definition of Done — Sessione 7 (= Definition of Done Fase 3):**
```
□ N-BEATS: fit + predict funzionanti su hardware reale (tempi documentati)
□ RealisticBacktester: visibile in Q1_Backtesting con breakdown costi
□ FastAPI: tutti gli endpoint documentati in CLAUDE.md
□ Metriche avanzate: dashboard Q1 mostra SMAPE, Theil's U, CRPS
□ Diagnostica residui: semaforo visibile nella pagina Q1
□ mypy --strict su api/: 0 errors
□ pytest --cov --cov-fail-under=89: verde
□ pytest -m regression: 0 failed
□ CLAUDE.md: sezione aggiornata con tutti i nuovi moduli v14
□ Nessuna regressione su pagine E*, K*, M*, Q* esistenti
```

---

## 📁 Struttura File Finale v14.0.0

```
%APPDATA%\MarketAI\
├── engine/analytics/
│   ├── forecasting/
│   │   └── nbeats/              ★ NUOVO
│   │       ├── nbeats_block.py
│   │       ├── nbeats_stack.py
│   │       ├── nbeats_model.py
│   │       └── ram_check.py
│   ├── backtesting/
│   │   ├── realistic_backtester.py  ★ NUOVO
│   │   ├── cost_model.py            ★ NUOVO
│   │   ├── liquidity_filter.py      ★ NUOVO
│   │   └── backtest_report.py       ★ NUOVO
│   └── evaluation/
│       ├── advanced_metrics.py      ★ NUOVO
│       ├── residual_diagnostics.py  ★ NUOVO
│       ├── diagnostic_report.py     ★ NUOVO
│       └── model_comparison.py      ★ NUOVO
├── api/                         ★ NUOVO
│   ├── main.py
│   ├── auth.py
│   └── routes/
│       ├── predict.py
│       ├── backtest.py
│       ├── models.py
│       └── health.py
└── tests/
    ├── engine/
    │   ├── forecasting/test_nbeats*.py     ★ NUOVO
    │   ├── backtesting/test_realistic*.py  ★ NUOVO
    │   └── evaluation/test_metrics*.py     ★ NUOVO
    └── api/test_*.py                       ★ NUOVO
```

---

## 📊 Metriche di Successo v14.0.0

| Metrica | Target | Note hardware |
|---------|--------|---------------|
| N-BEATS fit (128 hidden, 500 punti) | < 3 min | CPU Ryzen 5 5600 |
| N-BEATS predict (30 giorni) | < 5s | CPU |
| RAM durante N-BEATS training | < 3GB | 16GB totali |
| Backtesting AAPL 10 anni | < 10s | VectorBT su CPU |
| equity_net < equity_gross | 100% dei test | Regola 23 |
| FastAPI /predict XGBoost | < 10s | CPU |
| FastAPI /health | < 50ms | — |
| Coverage api/ | ≥ 90% | — |
| Coverage evaluation/ | 100% | — |
| pytest regression | 0 failed | SEMPRE |

---

*MarketAI v14.0.0 · Roadmap Fase 3 — Modelli Avanzati e Backtesting Realistico*  
*Pianificazione: Claude Sonnet 4.6 · Implementazione: Claude Code Pro (Opus 4.8)*  
*Hardware: Ryzen 5 5600 · RX 6700 8GB · 16GB RAM · CPU-only PyTorch*
