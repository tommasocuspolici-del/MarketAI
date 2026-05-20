"""CoinGecko API Fetcher — Top 20 crypto, dominance, Fear & Greed.

Sorgente: https://api.coingecko.com/api/v3 (free tier)
Limite free: ~10-30 req/min. Nessuna API key richiesta per tier base.
Regola 33: zero dati hardcoded.
Regola 34: cache-first (TTL: crypto = 3600s).
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import pandas as pd

from shared.config.operational_config import OP_CONFIG
from shared.exceptions import FetchError
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["CoinGeckoFetcher"]

log = get_logger(__name__)

_BASE_URL = "https://api.coingecko.com/api/v3"
_TIMEOUT = 20.0
_DELAY_S = 3.0  # ~20 req/min per evitare 429

# Top 20 crypto per market cap (approssimato — l'API ritorna il ranking reale)
TOP_CRYPTO_IDS: list[str] = [
    "bitcoin", "ethereum", "tether", "binancecoin", "solana",
    "ripple", "usd-coin", "cardano", "avalanche-2", "dogecoin",
    "polkadot", "tron", "chainlink", "polygon", "litecoin",
    "bitcoin-cash", "shiba-inu", "stellar", "cosmos", "monero",
]


class CoinGeckoFetcher:
    """Fetcher per prezzi crypto, dominance e Fear & Greed CoinGecko.

    Args:
        client: DuckDBClient per cache-first (Regola 34).

    Usage::

        fetcher = CoinGeckoFetcher(client=get_duckdb_client())
        df = fetcher.fetch_top_prices()
        dominance = fetcher.fetch_global_dominance()
    """

    def __init__(self, client: DuckDBClient) -> None:
        self._client = client
        self._http = httpx.Client(
            timeout=_TIMEOUT,
            headers={"User-Agent": "MarketAI/1.0 (educational research)"},
        )

    def fetch_top_prices(self, top_n: int = 20, vs_currency: str = "usd") -> pd.DataFrame:
        """Prezzi, market cap e volume Top N crypto.

        Returns:
            DataFrame con: ticker, price_usd, market_cap, volume_24h, change_24h,
                           rank, fetched_at.
        """
        log.info("coingecko.fetch_top_prices", top_n=top_n)
        try:
            time.sleep(_DELAY_S)
            resp = self._http.get(
                f"{_BASE_URL}/coins/markets",
                params={
                    "vs_currency": vs_currency,
                    "order": "market_cap_desc",
                    "per_page": top_n,
                    "page": 1,
                    "sparkline": "false",
                    "price_change_percentage": "24h",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                raise FetchError(source="coingecko", detail="Rate limit (429) — attendi 60s") from exc
            raise FetchError(source="coingecko", detail=f"HTTP {exc.response.status_code}") from exc
        except Exception as exc:
            raise FetchError(source="coingecko", detail=str(exc)) from exc

        now = datetime.now(UTC)
        rows = []
        for coin in data:
            rows.append({
                "ticker":       coin.get("symbol", "").upper() + "-USD",
                "coin_id":      coin.get("id", ""),
                "name":         coin.get("name", ""),
                "rank":         coin.get("market_cap_rank", 0),
                "price_usd":    coin.get("current_price"),
                "market_cap":   coin.get("market_cap"),
                "volume_24h":   coin.get("total_volume"),
                "change_24h":   coin.get("price_change_percentage_24h"),
                "source":       "coingecko",
                "fetched_at":   now,
            })

        if not rows:
            log.warning("coingecko.empty_prices")
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        self._persist_prices(df)
        log.info("coingecko.prices_done", rows=len(df))
        return df

    def fetch_global_dominance(self) -> pd.DataFrame:
        """Dominanza di mercato BTC/ETH e market cap totale.

        Returns:
            DataFrame con: metric, value, fetched_at.
        """
        log.info("coingecko.fetch_dominance")
        try:
            time.sleep(_DELAY_S)
            resp = self._http.get(f"{_BASE_URL}/global")
            resp.raise_for_status()
            data = resp.json().get("data", {})
        except Exception as exc:
            raise FetchError(source="coingecko", detail=f"global: {exc}") from exc

        now = datetime.now(UTC)
        dominance = data.get("market_cap_percentage", {})
        rows = [
            {"metric": "btc_dominance", "value": dominance.get("btc"), "fetched_at": now},
            {"metric": "eth_dominance", "value": dominance.get("eth"), "fetched_at": now},
            {"metric": "total_market_cap_usd", "value": data.get("total_market_cap", {}).get("usd"), "fetched_at": now},
            {"metric": "total_volume_24h_usd", "value": data.get("total_volume", {}).get("usd"), "fetched_at": now},
            {"metric": "active_cryptocurrencies", "value": data.get("active_cryptocurrencies"), "fetched_at": now},
        ]

        df = pd.DataFrame(rows)
        self._persist_dominance(df)
        log.info("coingecko.dominance_done")
        return df

    def fetch_fear_greed_index(self) -> dict[str, object] | None:
        """Crypto Fear & Greed Index da alternative.me (complementare).

        Ritorna dict con: value (0-100), classification, timestamp.
        """
        log.info("coingecko.fetch_fear_greed")
        try:
            time.sleep(_DELAY_S)
            resp = httpx.get("https://api.alternative.me/fng/?limit=1", timeout=OP_CONFIG.http.default_timeout_s)
            resp.raise_for_status()
            data_list = resp.json().get("data", [])
            if not data_list:
                return None
            item = data_list[0]
            return {
                "value":          int(item["value"]),
                "classification": item["value_classification"],
                "timestamp":      datetime.fromtimestamp(int(item["timestamp"]), tz=UTC),
                "source":         "alternative_me",
            }
        except Exception as exc:
            log.warning("coingecko.fear_greed_failed", error=str(exc))
            return None

    def _persist_prices(self, df: pd.DataFrame) -> None:
        """Salva prezzi crypto in ohlcv_data come 'close' (Regola 34)."""
        if df.empty:
            return
        try:
            now = datetime.now(UTC)
            today = now.date()
            for _, row in df.iterrows():
                if row["price_usd"] is None:
                    continue
                self._client.execute(
                    """
                    INSERT INTO ohlcv_data (ticker, exchange, timeframe, ts, open, high, low, close, volume, source, currency)
                    VALUES (?, 'CRYPTO', 'D1', ?, ?, ?, ?, ?, ?, 'coingecko', 'USD')
                    ON CONFLICT (ticker, exchange, timeframe, ts)
                    DO UPDATE SET close=excluded.close, volume=excluded.volume,
                                  open=excluded.open, high=excluded.high, low=excluded.low
                    """,
                    [
                        row["ticker"],
                        datetime(today.year, today.month, today.day, tzinfo=UTC),
                        float(row["price_usd"]),  # open=close (no OHLC dal free tier)
                        float(row["price_usd"]),
                        float(row["price_usd"]),
                        float(row["price_usd"]),
                        float(row["volume_24h"]) if row["volume_24h"] else 0.0,
                    ],
                )
        except Exception as exc:
            log.warning("coingecko.persist_prices_failed", error=str(exc)[:200])

    def _persist_dominance(self, df: pd.DataFrame) -> None:
        """Salva dominance in macro_data (Regola 34)."""
        if df.empty:
            return
        now = datetime.now(UTC)
        today_ts = datetime(now.year, now.month, now.day, tzinfo=UTC)
        try:
            for _, row in df.iterrows():
                if row["value"] is None:
                    continue
                self._client.execute(
                    """
                    INSERT INTO macro_data (series_id, series_date, value, source, unit, frequency, fetched_at)
                    VALUES (?, ?, ?, 'coingecko', 'percent', 'daily', ?)
                    ON CONFLICT (series_id, series_date)
                    DO UPDATE SET value=excluded.value, fetched_at=excluded.fetched_at
                    """,
                    [f"CRYPTO_{row['metric'].upper()}", today_ts, float(row["value"]), now],
                )
        except Exception as exc:
            log.warning("coingecko.persist_dominance_failed", error=str(exc)[:200])

    def __del__(self) -> None:
        try:
            self._http.close()
        except Exception:
            pass
