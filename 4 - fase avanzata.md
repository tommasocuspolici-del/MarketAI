# Portfolio Optimization

**File sorgente:** `engine/risk/portfolio_optimizer.py`, `personal/allocator/`
**Librerie:** `cvxpy ^1.5`, `scipy.optimize`
**Introdotto in:** v10 (base)
**Scopo:** Ottimizzazione allocation e ribilanciamento guidato da profilo investitore

---

## Due livelli di ottimizzazione

MarketAI separa nettamente l'ottimizzazione **quantitativa** (engine) da quella **personalizzata** (personal):

```
engine/risk/portfolio_optimizer.py  ← frontiera efficiente, ottimizzazione quantitativa
personal/allocator/                 ← raccomandazioni filtrate per InvestorProfile
```

L'engine calcola la frontiera; il personal layer seleziona il punto sulla frontiera compatibile con il profilo dell'utente.

---

## Frontiera Efficiente (CVXPY)

```python
from engine.risk.portfolio_optimizer import EfficientFrontierOptimizer
import cvxpy as cp

optimizer = EfficientFrontierOptimizer()

# Ottimizzazione Sharpe massimo
weights_sharpe = optimizer.max_sharpe(
    expected_returns=mu,          # np.ndarray [n_assets]
    covariance_matrix=Sigma,      # np.ndarray [n_assets × n_assets]
    risk_free_rate=0.04,
    constraints={"long_only": True, "max_weight": 0.30}
)

# Ottimizzazione CVaR minimo (più robusta agli outlier)
weights_cvar = optimizer.min_cvar(
    returns_scenarios=returns_df,  # pd.DataFrame scenari
    confidence=0.95,
    constraints={"long_only": True}
)

# Frontiera completa (N punti)
frontier = optimizer.efficient_frontier(mu, Sigma, n_points=50)
# frontier: pd.DataFrame [n_points × (n_assets + 2)]
# colonne: w_AAPL, w_MSFT, ..., expected_return, volatility
```

---

## Formulazione CVXPY

```python
# Ottimizzazione Sharpe massimo (formulazione Markowitz)
n = len(mu)
w = cp.Variable(n)                        # pesi portafoglio

portfolio_return = mu @ w
portfolio_var    = cp.quad_form(w, Sigma)

objective = cp.Maximize(portfolio_return - risk_free_rate)  # numeratore Sharpe
constraints = [
    cp.sum(w) == 1,                       # pesi sommano a 1
    w >= 0,                               # long only
    w <= max_weight,                      # max concentrazione
    portfolio_var <= target_volatility,   # vincolo volatilità target
]

problem = cp.Problem(objective, constraints)
problem.solve(solver=cp.ECOS)             # solver CPU-compatible
```

**Nota hardware:** ECOS solver è CPU-based, non richiede GPU. Compatibile con setup Ryzen 5 5600.

---

## Personal Allocator

```python
# personal/allocator/portfolio_allocator.py
from personal.allocator.portfolio_allocator import PersonalPortfolioAllocator

allocator = PersonalPortfolioAllocator()
recommendation = allocator.suggest(
    investor_profile=profile,
    market_context=market_ctx,       # dal bridge
    current_portfolio=positions,
)
# recommendation.target_weights: dict[str, float]
# recommendation.rebalancing_trades: list[Trade]
# recommendation.efficiency_score: float [0,1]
# recommendation.rationale: str (testo spiegazione)
```

**Regola:** Ogni raccomandazione è filtrata da `InvestorProfile`. Il punto sulla frontiera viene selezionato in base a `risk_tolerance` e `max_drawdown_pct`.

---

## Rebalancing Advisor

```python
# personal/allocator/rebalancing_advisor.py
advisor = RebalancingAdvisor(threshold=0.05)  # 5% drift trigger
advice = advisor.check(current_weights, target_weights)

# advice.needs_rebalancing: bool
# advice.drift_by_asset: dict[str, float]  ← quanto si è spostato ogni asset
# advice.suggested_trades: list[Trade]
# advice.estimated_cost: float             ← costo stimato del rebilanciamento
```

Il rebalancing viene suggerito quando un asset si discosta di > 5% dal target (configurabile).

---

## Efficiency Scorer

```python
# personal/allocator/efficiency_scorer.py
scorer = EfficiencyScorer()
score = scorer.compute(current_weights, frontier)
# score: float [0,1]
# 1.0 = portafoglio sulla frontiera efficiente
# 0.5 = portafoglio a metà strada tra il peggiore e il migliore
```

Mostrato in P2 Portfolio eToro come "Efficienza Portafoglio".

---

## Persistenza

```python
# I risultati dell'ottimizzazione NON vengono persistiti su DuckDB (computazione stateless)
# Solo le raccomandazioni di rebalancing vengono loggiate su SQLite (personal layer)
# tabella: rebalancing_history (user_sessions.db)
```

---

## Test

```
tests/engine/risk/test_portfolio_optimizer.py
  - test_weights_sum_to_one: somma pesi = 1.0 (tolleranza 1e-6)
  - test_long_only_constraint: tutti i pesi ≥ 0
  - test_max_weight_constraint: nessun peso > max_weight
  - test_sharpe_gt_zero: Sharpe ottimizzato > 0 su dati storici reali (AAPL, MSFT, SPY)
  - test_cvar_leq_var: CVaR ≥ VaR per definizione
  - test_frontier_has_n_points: frontiera restituisce esattamente N punti
```

---

## Anti-pattern

```
❌ Ottimizzazione senza vincolo long-only per profilo conservativo
   → Verificare InvestorProfile.allowed_asset_classes prima di abilitare short

❌ Frontiera calcolata senza regime-conditional correlations
   → Usare DCC-GARCH o rolling correlation condizionale per regime corrente

❌ Rebalancing suggerito senza stimare i costi
   → RebalancingAdvisor.estimated_cost sempre incluso nella raccomandazione

❌ Raccomandazione senza filtro InvestorProfile
   → SuitabilityChecker.check() sempre prima di mostrare suggerimento
```

---

## Pagine dashboard

- **Q4 Portfolio Optimizer** — frontiera efficiente interattiva
- **P2 Portfolio eToro** — efficiency score del portafoglio corrente
- **P7 Scenari Ricchezza** — allocazione ottimale per scenario
- **P6 Profilo Investitore** — confronto allocazione reale vs profilo consigliato

---

## Target performance

| Operazione | Target | Note |
|---|---|---|
| Ottimizzazione Sharpe (20 asset) | < 2s | ECOS solver CPU |
| Frontiera efficiente (50 punti, 20 asset) | < 10s | CPU |
| Efficiency scorer | < 100ms | — |

---

## Glossario

| Termine | Definizione |
|---|---|
| **Frontiera efficiente** | Insieme di portafogli con massimo rendimento per dato livello di rischio |
| **CVaR (Expected Shortfall)** | Media delle perdite oltre il VaR — più conservativa del VaR |
| **ECOS** | Embedded Conic Solver — solver CPU-based usato da CVXPY |
| **Drift** | Scostamento dei pesi correnti dai pesi target |
| **Rebalancing** | Operazione di riallineamento dei pesi al target |

---

## Collegamenti

- [[Risk Scoring]] — CVaR alimenta il risk score
- [[Correlation Engine]] — matrice di covarianza per la frontiera
- [[Market Regime]] — regime influenza i parametri di ottimizzazione
- [[BaseModel Interface]] — raccomandazioni usano previsioni dei modelli
