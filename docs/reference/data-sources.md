# Data Sources

Complete list of data sources, rate limits, and costs for the engine layer.

| Source | Tier | Req/Min | Req/Day | Cost | Use |
|--------|------|---------|---------|------|-----|
| **FRED** | Free | 120 | Unlimited | $0 | Macro 600+ series |
| **Yahoo Finance** | Free | ~60 | ~2000 | $0 | Daily OHLCV |
| **Finnhub** | Free | 60 | 5,000 | $0 | Real-time, news, sentiment |
| **Finnhub** | Starter | 300 | 100,000 | ~$25/mo | Production WebSocket |
| **Alpha Vantage** | Free | **5** | 500 | $0 | Fallback only (slow!) |
| **Alpha Vantage** | Premium | 75 | 5,000 | $50/mo | If primary |
| **SEC EDGAR** | Free | 10 | Unlimited | $0 | Fundamentals XBRL |
| **ECB / Eurostat** | Free | ~30 | Unlimited | $0 | EU macro |
| **World Bank** | Free | ~30 | Unlimited | $0 | Global macro |
| **BLS** | Free | 25 | 500 | $0 | US labor stats |
| **IMF** | Free | 10 | Unlimited | $0 | Cross-country |
| **Ollama** | Self-host | N/A | N/A | $0 | LLM narratives |

## Personal Use Estimate

- **Initial bulk download**: ~2h rate-limited
- **Daily operations**: < 500 calls/day across sources
- **Monthly cost**: **$0** with free tiers + aggressive caching

## When to Upgrade

- Real-time WebSocket > 1 ticker → Finnhub Starter
- Backtest universe > 500 tickers → Alpha Vantage Premium for fundamentals
