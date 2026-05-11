# Engine Layer

The `engine/` package is responsible for ALL quantitative analytics.
It never imports `personal/` directly.

## Sub-packages

```
engine/
├── market_data/        Fetchers + cleaners + quality reports
│   ├── fetchers/       Yahoo, FRED, EDGAR, Finnhub, Alpha Vantage
│   ├── cleaning/       Gap fill, outlier detection, stale check
│   └── base_fetcher.py Pipeline orchestrator (Rule 12)
├── market_registry/    Symbol resolution + exchange mapping
├── analytics/
│   ├── sentiment/      8-source aggregator + contrarian signals
│   ├── correlation/    DCC-GARCH-lite + HMM regime + lead-lag
│   └── pipeline/       End-to-end orchestrator
├── backtesting/        VectorBT-API engine + 5 strategies + walk-forward
├── stress_testing/     4 historical + 6 forward-looking scenarios
├── forecasting/        ARIMA/Prophet + 3-scenario projection
└── alerts/             YAML rule engine + dedup
```

## Key Classes

| Class | Module | Purpose |
|-------|--------|---------|
| `BaseFetcher` | `market_data.base_fetcher` | Abstract fetcher base |
| `DataCleaner` | `market_data.cleaning.cleaner` | Gap/outlier/stale (Rule 14) |
| `BacktestEngine` | `backtesting.engine` | Vectorized backtest runner |
| `StressTester` | `stress_testing.tester` | Historical + synthetic scenarios |
| `SentimentAggregator` | `analytics.sentiment` | 8-source composite |
| `CorrelationAnalyzer` | `analytics.correlation` | Static + rolling + EWMA + lead-lag |
| `RegimeDetector` | `analytics.correlation` | K-means HMM-lite |
| `AnalysisPipeline` | `analytics.pipeline` | End-to-end orchestrator |
| `RuleEngine` | `alerts.rule_engine` | YAML alerts + dedup |

## Data Pipeline (Rule 12)

```
fetch → clean → validate (Pandera) → duckdb_write → cache → return
```

This order is **invariable**. Every fetcher inherits from `BaseFetcher`
and follows it.
