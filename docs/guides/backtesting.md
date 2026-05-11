# Backtesting Guide

The `engine/backtesting/` module is VectorBT-API compatible (numpy-native
under the hood) and enforces Rule 23 invariants:

- **Fees** — minimum 0.001 (0.1%)
- **Slippage** — minimum 0.001 (0.1%)
- **Anti-look-ahead** — every signal `.shift(1)` before evaluation
- **Walk-forward** for any model comparison

## Quickstart

```python
from engine.backtesting import BacktestEngine, MovingAverageCrossover

engine = BacktestEngine(initial_cash=10_000.0)
strategy = MovingAverageCrossover(fast=20, slow=50)
result = engine.run(ohlcv_df, strategy, ticker="AAPL")

print(f"Sharpe: {result.performance.sharpe_ratio:.2f}")
print(f"Max DD: {result.performance.max_drawdown:.2%}")
print(f"Total Return: {result.performance.total_return:.2%}")
```

## Walk-Forward

```python
from engine.backtesting import walk_forward

splits = walk_forward(
    ohlcv_df, strategy,
    n_splits=5, train_window_days=252, test_window_days=63,
)
for i, split_result in enumerate(splits):
    print(f"Split {i}: Sharpe = {split_result.performance.sharpe_ratio:.2f}")
```

## Built-in Strategies

- `MovingAverageCrossover(fast, slow)` — classic MA cross
- `RSIMeanReversion(period, oversold, overbought)` — RSI mean reversion
- `MomentumBreakout(window)` — Donchian-style breakout
- `MacroFilter(...)` — Combined with macro regime filter
- `CombinedSignal(...)` — Weighted ensemble of multiple strategies

## Performance Targets

| Operation | Target | Actual |
|-----------|--------|--------|
| Single backtest 10y | < 2s | ~150ms |
| Walk-forward 5 splits | < 15s | ~3s |
| 5 strategies × 100 tickers | < 5min | ~90s |
