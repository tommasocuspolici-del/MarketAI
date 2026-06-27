**Introdotto in:** v14 – Modelli Avanzati (Sessione 3)  
**File sorgente:** `engine/analytics/backtesting/realistic_backtester.py`  
**Stato:** Simulatore a eventi con costi reali

## Panoramica

`RealisticBacktester` sostituisce il backtester semplificato con una simulazione a eventi che modella accuratamente i costi di trading: commissioni, slippage e vincoli di liquidità. L'equity curve viene calcolata sia lorda (prima dei costi) che netta (dopo tutti i costi), in modo da fornire una valutazione realistica delle performance.

## Componenti

### 1. CostModel (`cost_model.py`)
Modella commissioni e slippage.

- **Commissioni:** Percentuali o fisse.
  - Default: 0.1% per trade (`percentage`, `commission_value=0.001`).
  - Minimo assoluto: 0.1% (**Regola 23**).
  - Commissione minima: 1.00 EUR (per evitare commissioni irrisorie).

- **Slippage:** Basato sulla volatilità corrente.
  - Default: `slippage = price * volatility * 0.5`.
  - Minimo assoluto: 0.1% (se `slippage_type="fixed"`).

### 2. LiquidityFilter (`liquidity_filter.py`)
Limita la dimensione dell'ordine in base al volume giornaliero.

- **Default:** Max 5% del volume medio giornaliero.
- **Se superato:** L'ordine viene ridimensionato (parziale esecuzione).

### 3. RealisticBacktester (`realistic_backtester.py`)
Motore principale.

- **Input:** Prezzi storici, segnali (shiftati di 1), volume opzionale.
- **Output:** `BacktestResult` con equity curve lorda/netta, Sharpe lordo/netto, breakdown costi, max drawdown, win rate, profit factor.

## Regole di progettazione

|Regola|Descrizione|
|---|---|
|**R23 – Costi minimi**|Commissioni e slippage ≥ 0.001 (0.1%). Nessun backtest senza costi.|
|**R29 – No look-ahead**|I segnali devono essere shiftati di 1 (`signal.shift(1)`).|
|**Equity netta**|`equity_net = equity_gross - total_costs` sempre.|
|**Breakdown**|Report dettagliato per ogni operazione (commissione, slippage, prezzo eseguito).|

## Performance

- **AAPL 10 anni daily:** < 10 secondi su CPU.
    
- **Breakdown:** Report generato in < 1 secondo per 5000 operazioni.
    

## Test

- **Equity netta ≤ lorda:** Verificato su tutti i test.
    
- **Costi minimi:** `CostConfig.__post_init__` blocca se < 0.001.
    
- **Copertura:** 100% su `cost_model.py` e `realistic_backtester.py`.
    

## Collegamenti
    
- [[Engine Overview]]
    
- [[Data Flow]]
    

## Utilizzo

```python
from engine.analytics.backtesting.realistic_backtester import RealisticBacktester
from engine.analytics.backtesting.cost_model import CostConfig

config = CostConfig(
    commission_type="percentage",
    commission_value=0.001,      # 0.1%
    slippage_type="volatility",
    slippage_vol_multiplier=0.5,
)
backtester = RealisticBacktester(cost_config=config, initial_capital=10000.0)
result = backtester.run(prices=prices, signals=signals.shift(1), volume=volume)

print(f"Sharpe lordo: {result.sharpe_ratio:.2f}")
print(f"Sharpe netto: {result.sharpe_ratio_net:.2f}")
print(f"Costi totali: {result.total_cost:.2f} EUR")
