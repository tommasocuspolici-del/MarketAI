# Risk Scoring

**File sorgente:** `engine/risk/risk_scorer.py`, `engine/risk/portfolio_risk.py`
**Introdotto in:** v10 (base)
**Regola critica:** `❌ RiskScore senza breakdown → componenti sempre esposti`

---

## Panoramica

Il Risk Scoring produce un punteggio composito [0, 1] che rappresenta il rischio totale del portafoglio/mercato, con breakdown obbligatorio per componente. Un RiskScore senza breakdown non è accettabile nel codebase (anti-pattern esplicito nelle 32 regole).

---

## RiskScore composito

```python
@dataclass
class RiskScore:
    total: float                    # [0, 1] — 0 = rischio minimo, 1 = massimo
    breakdown: dict[str, float]     # componenti sempre esposti (obbligatorio)
    regime: str                     # regime di mercato corrente
    timestamp: datetime

    def __post_init__(self):
        assert 0.0 <= self.total <= 1.0, "RiskScore fuori range [0,1]"
        assert len(self.breakdown) >= 2, "Breakdown deve avere almeno 2 componenti"
        assert abs(sum(self.breakdown.values()) - self.total) < 1e-6, \
            "Somma breakdown deve essere uguale a total"
```

---

## Componenti del breakdown

| Componente | Peso default | Fonte dati | Range |
|---|---|---|---|
| `market_risk` | 35% | VIX, regime HMM, volatilità rolling | [0, 1] |
| `credit_risk` | 25% | Spread HY vs IG, CDS index | [0, 1] |
| `liquidity_risk` | 20% | Volume, bid-ask spread, put/call ratio | [0, 1] |
| `concentration_risk` | 20% | Herfindahl index del portafoglio | [0, 1] |

Esempio output:
```python
score = RiskScore(
    total=0.62,
    breakdown={
        "market_risk":       0.22,  # 35% × 0.62 ≈
        "credit_risk":       0.15,
        "liquidity_risk":    0.13,
        "concentration_risk": 0.12,
    },
    regime="bear",
    timestamp=datetime.utcnow(),
)
```

---

## Metriche di rischio portafoglio

```python
from engine.risk.portfolio_risk import PortfolioRiskEngine

engine = PortfolioRiskEngine()
metrics = engine.compute(returns_df, weights, confidence=0.95)

# metrics.var_95:       float — Value at Risk 95% (perdita massima in 1 giorno con P=95%)
# metrics.cvar_95:      float — CVaR (Expected Shortfall) — media perdite oltre VaR
# metrics.beta:         float — Beta rispetto a SPY o benchmark configurato
# metrics.sharpe:       float — Sharpe ratio annualizzato
# metrics.max_drawdown: float — massimo drawdown storico
# metrics.correlation_matrix: pd.DataFrame — usata per frontiera efficiente
```

---

## Suitability Check (Personal Layer)

Il `RiskScore` del mercato viene confrontato con il `max_drawdown_pct` dell'`InvestorProfile`:

```python
# bridge: engine → personal
from personal.investor_profile.suitability_checker import SuitabilityChecker

checker = SuitabilityChecker()
ok = checker.check(
    instrument_ticker="BTC-USD",
    asset_class="crypto",
    expected_max_drawdown=0.60,       # da RiskScore
    investor_profile=profile,
)
# ok = False → l'utente conservativo non può ricevere questo suggerimento
```

**Regola anti-pattern:** `❌ Suggerimento senza profilo → InvestorProfile sempre`

---

## Dove viene visualizzato

- **E1 Market Overview** — top 3 risk factors dal breakdown
- **P2 Portfolio eToro** — VaR, CVaR, Beta, Sharpe del portafoglio personale
- **K1 Composite Signal** — risk score come componente del segnale
- **Q3 Correlations** — correlazioni alimentano `concentration_risk`

---

## Test

```
tests/engine/risk/test_risk_scorer.py
  - test_score_range: RiskScore.total sempre in [0, 1]
  - test_breakdown_sums_to_total: somma componenti = total (tolleranza 1e-6)
  - test_stress_regime_increases_market_risk: market_risk > 0.5 in regime stress
  - test_cvar_geq_var: CVaR ≥ VaR per definizione matematica
  - test_suitability_blocks_aggressive_for_conservative: suitability check funziona
```

---

## Anti-pattern

```
❌ RiskScore.breakdown assente o vuoto
   → Breakdown obbligatorio con almeno 2 componenti — anti-pattern esplicito

❌ VaR calcolato senza considerare le code (fat tails)
   → Usare CVaR (Expected Shortfall) per una stima più conservativa

❌ Suggerimento di investimento senza SuitabilityCheck
   → SuitabilityChecker.check() sempre prima di qualsiasi raccomandazione
```

---

## Collegamenti

- [[Market Analysis Engine]] — contesto architetturale
- [[Market Regime]] — regime influenza market_risk
- [[Correlation Engine]] — correlazioni per concentration_risk
- [[Portfolio Optimization]] — CVaR ottimizzazione
