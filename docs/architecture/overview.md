# Architecture Overview

Market Analysis AI is built around **three independent layers** plus a
**bridge** that connects them. No layer imports from another except via
the bridge (Rule 21).

## High-Level Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    MARKET ANALYSIS AI  v6.0                               │
│                                                                            │
│  ┌─────────────────────────┐         ┌──────────────────────────────┐     │
│  │   🔬 ENGINE LAYER         │         │   💰 PERSONAL LAYER           │     │
│  │  (Quantitative Analysis)  │◄───────►│  (Personal Finance)          │     │
│  │                           │ bridge/ │                              │     │
│  │  · Market Data            │         │  · Portfolio (eToro)         │     │
│  │  · Analytics              │         │  · Cash Flow                 │     │
│  │  · Backtesting            │         │  · Net Worth                 │     │
│  │  · Stress Testing         │         │  · Goals (SMART)             │     │
│  │  · Forecasting            │         │  · Investor Profile          │     │
│  │  · Sentiment (8 sources)  │         │  · Wealth Scenarios          │     │
│  │  · Correlation/Regime     │         │  · Tax (IT regime)           │     │
│  │  · Pipeline orchestrator  │         │  · FIRE calculator           │     │
│  └──────────┬────────────────┘         └──────────────┬───────────────┘     │
│             │                                          │                     │
│             └──────────────────┬───────────────────────┘                     │
│                                │                                              │
│                  ┌─────────────▼──────────────┐                               │
│                  │   🌉 BRIDGE LAYER            │                               │
│                  │  bridge/api_contracts.py    │                               │
│                  │  bridge/engine_client.py    │                               │
│                  │  bridge/personal_client.py  │                               │
│                  └─────────────┬──────────────┘                               │
│                                │                                              │
│  ┌─────────────────────────────▼────────────────────────────────────────┐    │
│  │                       📦 SHARED LAYER                                 │    │
│  │  shared/types · exceptions · logger · rate_limit_manager             │    │
│  │  shared/feature_flags · health · backup_manager                      │    │
│  │                                                                        │    │
│  │  ┌──────────┐  ┌──────────┐  ┌────────────┐                          │    │
│  │  │  DuckDB  │  │  SQLite  │  │  diskcache │                          │    │
│  │  │  (OLAP)  │  │  (OLTP)  │  │  (TTL)     │                          │    │
│  │  └──────────┘  └──────────┘  └────────────┘                          │    │
│  └────────────────────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────────────────┘
```

## Core Principles

1. **Layer separation (Rule 21)**: `engine/` never imports `personal/` and
   vice versa. Communication goes ONLY through Pydantic contracts in
   `bridge/api_contracts.py`.

2. **Storage split (Rule 13)**:
   - **DuckDB** for analytical, time-series, append-mostly data: prices,
     macro, fundamentals, sentiment, backtest results, quality reports.
   - **SQLite** for transactional, mutable, profile-bound data: investor
     profiles, positions, cash flow entries, goals, snapshots.

3. **Data pipeline order (Rule 12)** is invariable:
   `fetch → clean → validate → duckdb_write → cache → return`

4. **Quality everywhere (Rule 26)**: every time series carries a
   `DataQualityReport` with a score in [0, 1]. Series with score < 0.7
   cannot enter critical calculations without explicit override.

## Build Layers Bottom-Up

### `shared/` — Foundation
Types, exceptions, logger, DB clients, cache, feature flags, rate limiter,
backup, health checks, metrics. **Imported by everyone**, depends on no
internal layer.

### `engine/` — Analytics
Reads market data, computes metrics, runs backtests/stress tests/pipelines.
Stateless functions; persistence delegated to `shared/db/*`.

### `personal/` — Finance
Owns the user's data: profile, portfolio, goals, tax. Reads market context
ONLY via `bridge/EngineClient`.

### `bridge/` — Pydantic frontier
The single boundary between `engine/` and `personal/`. Every cross-layer
call passes through a frozen Pydantic contract; schema violations raise
`ContractViolationError`.

### `presentation/` — Streamlit dashboards
Two independent Streamlit apps:

- `dashboard_engine/` — 14 analytical pages (E1–E14)
- `dashboard_personal/` — 9 personal-finance pages (P1–P9)

Both share the `presentation/ui/` library: theme, layout, 16 reusable
components.

## Trace a Request

A user opens **P7 — Wealth Scenarios** and asks "what's my Monte Carlo
projection?":

```
User clicks "Simulate" in P7
  ↓
Page calls personal/wealth_scenarios/WealthSimulator.simulate(...)
  ↓
WealthSimulator needs market parameters (expected return, volatility)
  ↓
Personal calls bridge/EngineClient.get_market_context()
  ↓
EngineClient invokes the injected producer (resolves engine.analytics
internally — but personal/ doesn't see this)
  ↓
Producer returns a dict matching MarketContextForPersonal contract
  ↓
EngineClient validates dict against the Pydantic contract
  ↓
WealthSimulator runs 10k log-normal simulations (numpy vectorized)
  ↓
Result returns to P7 page → wealth_scenario_chart component renders
the fan chart with P10/P50/P90 bands
```

## See Also

- [Engine Layer Detail](engine.md)
- [Personal Layer Detail](personal.md)
- [Bridge Contracts](bridge.md)
- [Data Layer (DuckDB + SQLite)](data-layer.md)
- [Observability & Health](observability.md)
