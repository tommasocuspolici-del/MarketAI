# Bridge & API Contracts

The bridge is the **single boundary** between `engine/` and `personal/`.
Rule 21 forbids any direct cross-layer import.

## Contracts (`bridge/api_contracts.py`)

All Pydantic models with `frozen=True, extra="forbid"`. Schema changes
require updating BOTH sides + contract tests.

| Contract | Direction | Purpose |
|----------|-----------|---------|
| `MarketContextForPersonal` | engine → personal | Risk-free rate, expected returns, vol, regime |
| `PortfolioSnapshotForEngine` | personal → engine | Portfolio for stress test / VaR |
| `PositionContract` | nested | Single position in a portfolio snapshot |
| `SuitabilityCheckRequest` | engine → personal | Validate instrument for a profile |
| `SuitabilityCheckResponse` | personal → engine | is_suitable + reasons + max weight |
| `StressTestRequest` | personal → engine | Scenario request with portfolio |
| `ForecastRequest` | personal → engine | Multi-scenario forecast request |
| `ForecastScenario` | nested | Single scenario in a forecast |

## Clients

- **`EngineClient`**: used by `personal/`. Wraps a producer callable that
  resolves engine internals; client validates the response against the
  contract.
- **`PersonalClient`**: used by `engine/` (e.g. for suitability checks
  during stress testing).

Both wrap producer errors in `ContractViolationError`.

## Why This Matters

Without the bridge, a refactor in `engine/` could silently break
`personal/`. With it, any contract violation surfaces immediately as a
test failure. The bridge gives us:

- Type safety across layers
- Refactor safety (contracts are the API)
- Clear ownership (each layer owns its own internals)
- Testability (mocking the bridge in unit tests is trivial)
