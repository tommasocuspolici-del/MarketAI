# Personal Layer

The `personal/` package owns the user's individual financial data:
profile, portfolio, goals, taxes. It NEVER imports `engine/` directly.

## Sub-packages

```
personal/
├── investor_profile/   Pydantic InvestorProfile + SQLite CRUD + suitability
├── wealth_scenarios/   Monte Carlo simulator + retirement (FIRE)
├── cashflow/           Entries + projector (12-month forecast)
├── networth/           Assets + liabilities + snapshots
├── goals/              SMART goals + progress + feasibility
└── tax/                Italian (26%) + EU generic regimes
```

## Data Owned (SQLite)

| Table | Retention | Purpose |
|-------|-----------|---------|
| `investor_profiles` | Permanent | Risk tolerance, horizon, allowed assets |
| `positions` | 10 years | Imported eToro positions |
| `cash_flow_entries` | 10 years | Income/expense entries |
| `financial_goals` | Permanent | SMART goal definitions |
| `wealth_snapshots` | 10 years | Periodic net worth captures |
| `assets` / `liabilities` | Current | For net worth computation |

## Rule 22 — Suitability Filter

EVERY suggestion to the user passes through `SuitabilityChecker`. Zero
exceptions. The checker validates against:

- Allowed asset classes (e.g. crypto blocked for "conservative" profile)
- Max acceptable drawdown
- Excluded sectors / countries
- Investment horizon vs. liquidity reserve

Violations raise `ProfileSuitabilityError`.
