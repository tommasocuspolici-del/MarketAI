# Backtesting Strategies

**File sorgente:** `engine/analytics/backtesting/`, `models/`
**Introdotto in:** v10 (base) · v14 (RealisticBacktester con costi)
**Regola critica:** `❌ Backtest senza commissioni/slippage → fees≥0.001, slippage≥0.001 sempre`

---

## Due engine di backtesting

MarketAI ha **due backtester** con scopi diversi — non sono intercambiabili:

| Engine | File | Quando usarlo | Velocità |
|---|---|---|---|
| **VectorBT** | `vectorbt` (libreria) | Test rapidi, ottimizzazione parametri, walk-forward | ⚡ Molto veloce (numpy) |
| **RealisticBacktester** | `engine/analytics/backtesting/realistic_backtester.py` | Simulazione production, report con breakdown costi | 🐢 Più lento, più accurato |

**Regola:** Mai loop Python su serie storiche → VectorBT o numpy vettorizzato sempre.

---

## Strategie esistenti nel codebase

### 1. MA Cross (Moving Average Crossover)

```python
# Segnale: EMA fast > EMA slow → long; EMA fast < EMA slow → short
signal = (ema_fast > ema_slow).astype(int) * 2 - 1    # +1 o -1
signal_shifted = signal.shift(1)                        # anti look-ahead bias (obbligatorio)
```

Parametri configurabili: `fast_window` (10), `slow_window` (30)

### 2. RSI Mean Reversion

```python
# RSI < 30 → oversold → long; RSI > 70 → overbought → short
rsi = ta.RSI(close, timeperiod=14)
signal = pd.Series(0, index=close.index)
signal[rsi < 30] = 1     # buy
signal[rsi > 70] = -1    # sell
signal_shifted = signal.shift(1)   # anti look-ahead bias
```

### 3. Momentum (Trend Following)

```python
# Rendimento 12 mesi > 0 → long; < 0 → short
momentum_12m = close / close.shift(252) - 1
signal = np.sign(momentum_12m).shift(1)   # shift obbligatorio
```

### 4. Macro Signal Strategy

```python
# Segnale basato su yield curve e PMI
# Yield curve normale + PMI > 50 → long
# Yield curve invertita o PMI < 50 → short
from engine.alpha_generation.yield_curve_signal import YieldCurveSignal
from engine.alpha_generation.macro_signal import MacroSignal

yield_sig = YieldCurveSignal().compute()
macro_sig  = MacroSignal().compute()
composite  = (yield_sig + macro_sig) / 2
signal     = np.sign(composite).shift(1)
```

### 5. Combined Strategy (Multi-factor)

Combina tecnico + macro + sentiment:

```python
signal = (
    0.40 * ma_cross_signal +
    0.30 * momentum_signal +
    0.20 * macro_signal +
    0.10 * sentiment_signal
).apply(np.sign).shift(1)
```

---

## CostConfig — parametri costi obbligatori

```python
from engine.analytics.backtesting.cost_model import CostConfig

config = CostConfig(
    commission_type="percentage",
    commission_value=0.001,       # 0.1% — MINIMO ASSOLUTO (Regola 23)
    slippage_type="volatility",
    slippage_pct=0.001,           # 0.1% fisso
    slippage_vol_multiplier=0.5,
    min_commission=1.0,           # EUR
    max_volume_fraction=0.05,     # max 5% volume giornaliero
)
```

**Regola 23:** `fees ≥ 0.001` e `slippage ≥ 0.001` sempre. `CostConfig.__post_init__` lancia ValueError se violata.

---

## Walk-Forward Validation

Obbligatoria per validare le strategie fuori campione:

```python
from vectorbt.generic.splitters import rolling_split

# 5 split: addestra su finestra crescente, testa su finestra futura
splits = rolling_split(
    data=df,
    n=5,
    window_len=252 * 3,    # 3 anni training
    set_lens=[252],        # 1 anno test
    left_to_right=True,
)

results = []
for train_idx, test_idx in splits:
    # Addestra su train, valuta su test
    pf = vbt.Portfolio.from_signals(
        close=df["Close"].iloc[test_idx],
        entries=signal.iloc[test_idx] == 1,
        exits=signal.iloc[test_idx] == -1,
        fees=0.001,
        slippage=0.001,
    )
    results.append(pf.sharpe_ratio())

# La strategia è valida se Sharpe medio > 0 su tutti i fold
```

---

## Anti-pattern

```
❌ Backtest senza commissioni/slippage
   → CostConfig con commission_value ≥ 0.001 e slippage_pct ≥ 0.001

❌ Segnale non shiftato di 1 periodo (look-ahead bias)
   → signal.shift(1) SEMPRE prima del backtest

❌ Confronto modelli in-sample
   → Walk-forward o purged k-fold obbligatorio

❌ Stress test solo storico
   → Aggiungere sempre scenari sintetici forward-looking

❌ Backtest senza DataQualityReport
   → Verificare quality_score > 0.7 prima del run
```

---

## Aggiungere una nuova strategia — Checklist

```
□ File: engine/analytics/backtesting/strategies/<nome>_strategy.py
□ Segnale: pd.Series con valori +1 (long) / -1 (short) / 0 (flat)
□ Anti look-ahead: signal.shift(1) prima del backtest
□ CostConfig: commissioni ≥ 0.001 e slippage ≥ 0.001
□ Walk-forward: almeno 3 split
□ Test: tests/engine/backtesting/test_<nome>_strategy.py
□ Registrare nel selettore della pagina Q1_Backtesting
□ pytest -m regression: 0 failed
```

---

## Target performance (Ryzen 5 5600)

| Operazione | Target |
|---|---|
| VectorBT backtest singolo ticker 10 anni | < 2s |
| Walk-forward 5 split VectorBT | < 15s |
| RealisticBacktester AAPL 10 anni | < 10s |

---

## Pagine dashboard

- **Q1 Backtesting** — backtest singolo con equity curve, metriche, walk-forward
- **Q2 Stress Test** — scenario testing con RealisticBacktester
- **Q12 Strategy Lab** — confronto multi-strategia

---

## Collegamenti

- [[Realistic Backtester]] — dettaglio del RealisticBacktester con costi
- [[Advanced Metrics]] — metriche di valutazione del backtest
- [[Market Regime]] — regime labeling per analisi condizionale
- [[Data Flow]] — come i dati entrano nel backtest
