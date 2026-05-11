# Configuration

All configuration lives in `config/`. YAML format throughout for
human-readability and version-control friendliness.

## Files

| File | Purpose |
|------|---------|
| `default.yaml` | Application defaults |
| `data_sources.yaml` | Endpoints + headers per source |
| `rate_limits.yaml` | Per-source rate budgets (Rule 28) |
| `feature_flags.yaml` | Toggle expensive/experimental features (Rule 29) |
| `data_retention.yaml` | Retention policy per table (Rule 31) |
| `data_quality.yaml` | Quality thresholds (Rule 26) |
| `risk_scoring.yaml` | Risk score weights |
| `alert_rules.yaml` | Declarative alert rules |
| `sentiment_sources.yaml` | Composite weights per source |
| `stress_scenarios.yaml` | Historical scenario definitions |
| `investor_profiles.yaml` | Default profile templates |
| `correlation_config.yaml` | EWMA lambda, lead-lag params |
| `backtesting.yaml` | Default fees, slippage, walk-forward |
| `ui_theme.yaml` | DESIGN_TOKENS for the dashboards (Rule 20) |

## See Also

- [Feature Flags](../reference/feature-flags.md)
- [Rate Limits](../reference/rate-limits.md)
- [Conventions](../reference/conventions.md)
