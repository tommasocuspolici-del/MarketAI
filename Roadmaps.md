# Market Regime — Rilevamento Regime di Mercato

**File sorgente:** `engine/analytics/` (HMM integrato nella pipeline)
**Libreria:** `hmmlearn ^0.3`
**Introdotto in:** v10 (base) · documentato completamente post-analisi vault v2
**Scopo:** Classificare il mercato in stati discreti per contestualizzare l'analisi

---

## Panoramica

Il sistema di Market Regime usa un **Hidden Markov Model (HMM)** per classificare lo stato corrente del mercato in uno di quattro regimi discreti. Questa classificazione è usata da quasi tutti i moduli dell'engine: correlazioni, stress test, alpha generation, alert.

---

## I 4 regimi

| Regime | Label | Caratteristiche tipiche | VIX tipico |
|---|---|---|---|
| `"bull"` | 0 | Trend rialzista, volatilità bassa, correlazioni ridotte | < 15 |
| `"bear"` | 1 | Trend ribassista, volatilità media, drawdown progressivo | 15–25 |
| `"transition"` | 2 | Cambio di regime, segnali misti, elevata incertezza | 20–30 |
| `"stress"` | 3 | Crisi acuta, volatilità massima, correlazioni vicine a 1 | > 30 |

---

## Input e output del modello HMM

**Input:** serie di rendimenti logaritmici giornalieri + VIX

```python
features = np.column_stack([
    np.log(prices / prices.shift(1)).dropna(),   # log-returns
    vix_series.dropna(),                          # VIX level
    rolling_vol_21d.dropna(),                     # volatilità rolling 21gg
])
```

**Output:** array di etichette per ogni giorno storico

```python
# hmmlearn usage (semplificato)
from hmmlearn.hmm import GaussianHMM

model = GaussianHMM(n_components=4, covariance_type="full", n_iter=100)
model.fit(features)
labels = model.predict(features)
# labels: np.ndarray[int]  — 0, 1, 2 o 3 per ogni trading day
```

**Regime corrente:** l'ultima label della serie è il regime attuale.

---

## Propagazione via SignalBus

Il regime corrente viene pubblicato sul `SignalBus` ad ogni aggiornamento della pipeline:

```python
# In engine/analytics/pipeline.py
from shared.signal_bus import SignalBus

regime = regime_detector.predict_current()
SignalBus.get_instance().publish(
    "regime_changed",
    payload={"regime": regime, "timestamp": datetime.utcnow().isoformat()}
)
```

**Consumatori del segnale `regime_changed`:**

| Consumatore | Effetto |
|---|---|
| `Correlation Engine` | Seleziona matrice di correlazione regime-conditional |
| `Alpha Generation` | Aggiusta i pesi dei segnali in base al regime |
| `Risk Scorer` | Aumenta `market_risk` in regime stress |
| `Stress Testing` | Seleziona/genera scenari pertinenti al regime |
| `E1 Dashboard` | Aggiorna il `regime_badge` in tempo reale |
| `Alert System` | Valuta se inviare alert "cambio regime" |

---

## MarketRegime nei bridge contracts

Il regime è incluso nel contratto `MarketContextForPersonal` per il layer Personal:

```python
# bridge/api_contracts.py
class MarketContextForPersonal(BaseModel):
    current_regime: str   # "bull" | "bear" | "transition" | "stress"
    vix: float
    ...
```

Il `WealthSimulator` usa il regime per selezionare i parametri di simulazione Monte Carlo:

```python
regime_params = {
    "bull":       {"return_mean": 0.10, "return_std": 0.12},
    "bear":       {"return_mean": -0.05, "return_std": 0.22},
    "transition": {"return_mean": 0.02, "return_std": 0.18},
    "stress":     {"return_mean": -0.20, "return_std": 0.40},
}
```

---

## Visualizzazione

Il regime corrente appare in dashboard come **regime_badge**:

```python
# presentation/ui/components/regime_badge.py
REGIME_COLORS = {
    "bull":       "#4CAF50",    # verde
    "bear":       "#f44336",    # rosso
    "transition": "#FF9800",    # arancio
    "stress":     "#9C27B0",    # viola
}
```

Visibile in: E1 Market Overview (sidebar), K1 Composite Signal, Q3 Correlations.

---

## Persistenza

```sql
-- DuckDB: tabella regime labels
CREATE TABLE market_regimes (
    date         DATE PRIMARY KEY,
    regime       VARCHAR NOT NULL,     -- "bull" | "bear" | "transition" | "stress"
    regime_id    INTEGER NOT NULL,     -- 0, 1, 2, 3
    confidence   DOUBLE,               -- probabilità HMM del regime assegnato
    vix          DOUBLE,
    computed_at  TIMESTAMPTZ NOT NULL
);
-- Retention: assimilato a prezzi storici (20 anni)
```

---

## Calibrazione e aggiornamento del modello HMM

Il modello HMM viene **ri-addestrato periodicamente** (non ad ogni aggiornamento):

```python
# Frequenza ri-addestramento: mensile (job APScheduler)
# Training window: ultimi 5 anni di dati daily
# Validazione: confronto regime labels con VIX thresholds manuali
```

**Problema dell'ordinamento stati:** HMM non garantisce che lo stato 0 = bull. Dopo ogni training si esegue un mapping manuale basato sulla volatilità media per stato:

```python
# Mean volatility per stato → ordina da bassa (bull) ad alta (stress)
state_volatilities = {s: vol_series[labels == s].mean() for s in range(4)}
sorted_states = sorted(state_volatilities, key=state_volatilities.get)
regime_map = {sorted_states[i]: ["bull","bear","transition","stress"][i] for i in range(4)}
```

---

## Test

```
tests/engine/analytics/test_market_regime.py
  - test_hmm_4_states: modello produce esattamente 4 stati distinti
  - test_stress_highest_volatility: regime "stress" ha volatilità media più alta
  - test_bull_lowest_volatility: regime "bull" ha volatilità media più bassa
  - test_regime_published_on_signal_bus: SignalBus.publish chiamato dopo predict
  - test_regime_in_bridge_contract: MarketContextForPersonal.current_regime valido
```

---

## Anti-pattern

```
❌ Confrontare correlazioni senza condizionare per regime
   → Usare sempre regime-conditional correlation in analisi approfondita

❌ Forzare manualmente l'etichetta di regime senza ri-addestrare HMM
   → Il mapping automatico (volatilità media) è il metodo corretto

❌ Usare il regime come variabile categorica senza encoding
   → Passare sempre la stringa ("bull" ecc.), non l'integer grezzo (0-3)

❌ Ignorare il regime nella generazione degli scenari di stress test
   → Il regime corrente influenza la selezione/generazione degli scenari
```

---

## Dove il regime influenza il sistema

```
Market Regime
    ├── → Correlation Engine  (seleziona matrice regime-conditional)
    ├── → Alpha Generation    (aggiusta pesi composite signal)
    ├── → Risk Scorer         (aumenta market_risk in stress)
    ├── → Stress Testing      (seleziona scenari pertinenti)
    ├── → WealthSimulator     (parametri Monte Carlo per regime)
    ├── → Alert System        (alert "cambio regime")
    └── → Dashboard E1, K1    (regime_badge UI)
```

---

## Glossario

| Termine | Definizione |
|---|---|
| **HMM** | Hidden Markov Model: modello probabilistico per sequenze di stati latenti |
| **n_components** | Numero di stati nascosti dell'HMM (= 4 in MarketAI) |
| **Regime label** | Stringa identificativa del regime: "bull" / "bear" / "transition" / "stress" |
| **Confidence** | Probabilità HMM del regime assegnato — bassa in periodi di transizione |
| **Regime mapping** | Conversione da integer HMM (0-3) a label semantica tramite volatilità media |

---

## Collegamenti

- [[Market Analysis Engine]] — contesto architetturale
- [[Correlation Engine]] — usa i regime labels per correlazioni condizionali
- [[Sentiment Engine]] — sentiment score influenza il regime rilevato
- [[Risk Scoring]] — regime alimenta il market_risk component
- [[Data Flow]] — posizione nella pipeline di analisi
