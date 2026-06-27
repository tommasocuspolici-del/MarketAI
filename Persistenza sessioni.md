# Correlation Engine

**Introdotto in:** v10 (rolling) · v12 (DCC-GARCH + HMM)
**File sorgente:** `engine/analytics/correlation/`
**Stato:** Correlazioni dinamiche regime-conditional tra asset class

---

## Panoramica

Il Correlation Engine calcola le correlazioni tra asset usando **tre approcci complementari**, scegliendo il più appropriato in base al contesto. Le correlazioni non sono statiche: cambiano significativamente tra regimi di mercato diversi (bull vs bear vs stress).

**Regola anti-pattern:** `❌ Correlazione senza regime → DCC-GARCH o rolling + HMM label sempre`

---

## I tre approcci

### 1. Rolling Correlation (veloce, sempre disponibile)

```python
from engine.analytics.correlation.rolling_correlation import RollingCorrelationEngine

engine = RollingCorrelationEngine(windows=[30, 90, 252])
matrix = engine.compute(returns_df)
# matrix.corr_30d: pd.DataFrame [n_assets × n_assets]
# matrix.corr_90d: pd.DataFrame
# matrix.corr_252d: pd.DataFrame (1 anno)
```

Usata per: dashboard real-time (E8), visualizzazione rapida, alert su variazioni anomale.

### 2. DCC-GARCH (accurata, più lenta)

**Dynamic Conditional Correlation** — stima correlazioni varianti nel tempo insieme alla volatilità condizionale.

```python
from engine.analytics.correlation.dcc_garch import DCCGARCHEngine

engine = DCCGARCHEngine()
result = engine.fit_predict(returns_df)
# result.conditional_correlations: np.ndarray [T × n × n]
# result.conditional_volatilities: np.ndarray [T × n]
# result.log_likelihood: float
```

Quando usarla:
- Analisi approfondita del portafoglio
- Stress test (correlazioni in scenari avversi aumentano — DCC lo cattura)
- Report periodico (non real-time, troppo lenta per aggiornamento continuo)

Target performance: < 10s su 20 asset con 5 anni di dati daily (Ryzen 5 5600).

### 3. Regime-Conditional Correlation (via HMM)

Calcola matrici di correlazione separate per regime di mercato, usando le etichette HMM:

```python
from engine.analytics.correlation.regime_conditional import RegimeConditionalCorrelation

engine = RegimeConditionalCorrelation()
result = engine.compute(returns_df, regime_labels)
# result.bull_correlation: pd.DataFrame    ← correlazioni in regime bull
# result.bear_correlation: pd.DataFrame    ← correlazioni in regime bear
# result.stress_correlation: pd.DataFrame  ← correlazioni in crisi (tipicamente più alte)
# result.transition_correlation: pd.DataFrame
```

Insight chiave: in regime **stress**, le correlazioni tra asset tradizionalmente decorrelati (es. azioni e oro) si avvicinano a 1.0 perché gli investitori vendono tutto per liquidità.

---

## Network Graph (NetworkX)

Il network graph mostra visivamente quali asset sono più "connessi" al sistema:

```python
from engine.analytics.correlation.network_builder import CorrelationNetworkBuilder

builder = CorrelationNetworkBuilder(correlation_threshold=0.5)
G = builder.build(corr_matrix)
# G: networkx.Graph
# G.nodes: asset (ticker)
# G.edges: correlazione > threshold
# Centralità: G.degree_centrality() → asset più connessi
```

Visualizzato in E8 Correlations con Plotly network graph.

---

## Granger Causality

Testa se un asset "anticipa" un altro (lead-lag):

```python
from engine.analytics.correlation.granger import GrangerCausalityTest

test = GrangerCausalityTest(max_lag=5)
result = test.compute(returns_df, asset_a="VIX", asset_b="SPY")
# result.p_value: float — se < 0.05 → VIX anticipa SPY (statisticamente)
# result.optimal_lag: int — di quanti periodi anticipa
```

---

## Struttura dati

```python
# Struttura output unificata
@dataclass
class CorrelationResult:
    method: str                          # "rolling_30d" | "dcc_garch" | "regime_bull"
    matrix: pd.DataFrame                 # matrice simmetrica [n × n]
    regime: str | None                   # regime HMM se applicabile
    computed_at: datetime
    n_observations: int
    quality_score: float                 # [0,1] — 1.0 = dati completi
```

---

## Persistenza (DuckDB)

```sql
-- Tabella correlazioni DuckDB
CREATE TABLE correlation_snapshots (
    snapshot_id  VARCHAR PRIMARY KEY,
    method       VARCHAR NOT NULL,    -- "rolling_90d" | "dcc_garch" | "regime_bear"
    asset_a      VARCHAR NOT NULL,
    asset_b      VARCHAR NOT NULL,
    correlation  DOUBLE NOT NULL,
    regime       VARCHAR,
    computed_at  TIMESTAMPTZ NOT NULL
);
-- Retention: 2 anni (assimilato a backtest_results)
```

---

## Pagine dashboard

- **E8 Correlations** — heatmap rolling, network graph, regime-conditional
- **Q3 Correlations** — DCC-GARCH interattivo, Granger causality
- **Q4 Portfolio Optimizer** — usa correlazioni per la frontiera efficiente

---

## Test

```
tests/engine/analytics/test_correlation_engine.py
  - test_rolling_matrix_symmetric: matrice simmetrica con diagonale 1.0
  - test_dcc_garch_performance: < 10s su 20 asset (pytest-benchmark)
  - test_regime_correlation_increases_in_stress: corr stress > corr bull
  - test_granger_lag_detection: VIX anticipa SPY su dati sintetici noti
```

---

## Anti-pattern

```
❌ Correlazione calcolata senza label di regime
   → Aggiungere sempre HMM label per regime-conditional output

❌ DCC-GARCH usata per aggiornamenti real-time
   → Usare rolling per RT, DCC solo per analisi batch

❌ Matrice di correlazione non simmetrica in output
   → Verificare con assert (matrix == matrix.T).all().all()
```

---

## Collegamenti

- [[Market Analysis Engine]] — contesto architetturale
- [[Market Regime]] — etichette HMM usate per regime-conditional
- [[Risk Scoring]] — correlazioni alimentano il risk score
- [[Portfolio Optimization]] — frontiera efficiente usa la matrice di correlazione
