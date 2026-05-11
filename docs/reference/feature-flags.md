# Feature Flags

`config/feature_flags.yaml` controls expensive/experimental features
(Rule 29). Default for ALL flags is `false`.

```yaml
edgar_bulk_download:    false   # First run manual, then scheduler
realtime_websocket:     true    # Finnhub WebSocket for live prices
pytorch_forecasting:    false   # DL models — RAM/CPU heavy
advanced_correlation:   true    # DCC-GARCH (full) + HMM (full)
ollama_narrative:       false   # LLM narratives — requires Ollama
personal_tax_report:    true    # IT capital gains computation
auto_rebalancing_alerts: true   # Portfolio rebalance alerts
```

Use in code:

```python
from shared.feature_flags import is_enabled, require_enabled

# Soft check
if is_enabled("ollama_narrative"):
    do_expensive_thing()

# Hard guard — raises FeatureDisabledError
def expensive_function():
    require_enabled("pytorch_forecasting")
    # ...
```
