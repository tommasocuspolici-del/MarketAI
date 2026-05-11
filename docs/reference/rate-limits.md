# Rate Limits

`config/rate_limits.yaml` — single source of truth for API rate budgets
(Rule 28). The `RateLimitManager` is the ONLY component that throttles
external API calls.

Example:

```yaml
finnhub:
  requests_per_minute: 60
  requests_per_day: 5000
  burst_size: 5

fred:
  requests_per_minute: 120
  requests_per_day: unlimited

alpha_vantage:
  requests_per_minute: 5
  requests_per_day: 500

yahoo_finance:
  requests_per_minute: 60
  requests_per_day: unlimited

sec_edgar:
  requests_per_minute: 10
  requests_per_day: unlimited
```

Use in fetcher:

```python
from shared.rate_limit_manager import RateLimitManager

rate_mgr = RateLimitManager()

async def fetch_one(ticker: str):
    await rate_mgr.acquire("finnhub")
    # ...HTTP call here...
```

The manager:

- Enforces per-minute and per-day budgets independently
- Auto-throttles (await) when limits are reached
- Raises `RateLimitExceededError` if daily budget exhausted
