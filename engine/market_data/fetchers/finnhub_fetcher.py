"""Finnhub fetcher — real-time OHLCV + news sentiment.

Finnhub offers two REST endpoints we care about:
  · /stock/candle   — OHLCV bars (free tier covers daily and intraday)
  · /news-sentiment — aggregated news sentiment score per ticker

The free tier limit is 60 req/min, 5 000 req/day. WebSocket streaming for
real-time ticks is gated by the ``realtime_websocket`` feature flag
(Rule 29) — disabled by default to avoid burning the daily budget.

API key read from ``FINNHUB_API_KEY`` env var (Rule 15).
Rate limits configured under ``finnhub`` in ``config/rate_limits.yaml`` (Rule 28).
"""
from __future__ import annotations

import os
from collections.abc import Mapping  # noqa: TC003
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import aiohttp
import pandas as pd

from engine.market_data.fetchers.base_fetcher import BaseOhlcvFetcher
from shared.exceptions import ConfigurationError, FetchError
from shared.feature_flags import is_enabled
from shared.logger import get_logger
from shared.metrics import metrics
from shared.rate_limit_manager import RateLimitManager, get_rate_limiter
from shared.types import DataSource, TimeFrame, ensure_utc

if TYPE_CHECKING:
    from engine.market_data.cleaning import DataCleaner
    from shared.db.dual_writer import DualWriter
    from shared.db.quality import QualityReportRepository

__version__ = "6.0.0"

__all__ = ["FinnhubFetcher", "NewsSentiment"]

log = get_logger(__name__)

_BASE_URL = "https://finnhub.io/api/v1"

# Mapping TimeFrame → "resolution" parameter accepted by Finnhub /stock/candle
_RESOLUTION_MAP: dict[str, str] = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "1d": "D",
    "1w": "W",
    "1mo": "M",
}


class NewsSentiment:
    """Lightweight value object representing a ticker-level sentiment score."""

    __slots__ = ("bearish_pct", "bullish_pct", "buzz_articles", "ticker", "ts")

    def __init__(
        self,
        ticker: str,
        ts: datetime,
        bullish_pct: float,
        bearish_pct: float,
        buzz_articles: int,
    ) -> None:
        self.ticker = ticker
        self.ts = ts
        self.bullish_pct = bullish_pct
        self.bearish_pct = bearish_pct
        self.buzz_articles = buzz_articles

    @property
    def composite_score(self) -> float:
        """Normalized sentiment in [-1, 1]: bullish > bearish → positive."""
        # Rule 8: usiamo float64 (numpy/scipy) per coerenza, ma uno score
        # puro in [-1, 1] è già adeguato per pandas a valle.
        return float(self.bullish_pct - self.bearish_pct)


class FinnhubFetcher(BaseOhlcvFetcher):
    """OHLCV + news sentiment via Finnhub REST.

    Inherits the Rule-12 pipeline from ``BaseOhlcvFetcher``: subclasses
    only fill in ``_fetch_raw_ohlcv``. News sentiment is exposed via the
    separate ``fetch_news_sentiment`` method (does not flow through
    Pandera/DuckDB persistence — sentiment goes into ``sentiment_observations``
    by the sentiment engine in Phase 8).
    """

    def __init__(
        self,
        rate_limiter: RateLimitManager | None = None,
        cleaner: DataCleaner | None = None,
        dual_writer: DualWriter | None = None,
        quality_repo: QualityReportRepository | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        super().__init__(
            source=DataSource.FINNHUB,
            rate_limiter=rate_limiter or get_rate_limiter(),
            cleaner=cleaner,
            dual_writer=dual_writer,
            quality_repo=quality_repo,
        )
        # Regola 15: API key da .env, mai hardcoded
        key = api_key or os.getenv("FINNHUB_API_KEY", "").strip()
        if not key:
            raise ConfigurationError(
                "FINNHUB_API_KEY environment variable is required for FinnhubFetcher."
            )
        self._api_key: str = key
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    # ─── OHLCV pipeline (delegated to BaseOhlcvFetcher) ─────────────────
    async def _fetch_raw_ohlcv(
        self,
        ticker: str,
        exchange: str,
        timeframe: TimeFrame,
        start: datetime | None,
        end: datetime | None,
    ) -> pd.DataFrame:
        """Fetch OHLCV bars from /stock/candle. No cleaning here."""
        tf_str = timeframe.value if isinstance(timeframe, TimeFrame) else str(timeframe)
        resolution = _RESOLUTION_MAP.get(tf_str)
        if resolution is None:
            raise FetchError(
                source=self.source,
                detail=f"unsupported timeframe '{tf_str}' for Finnhub",
            )

        # Finnhub usa epoch seconds. Default a ~5y se start/end mancano.
        end_epoch = int(ensure_utc(end).timestamp()) if end else int(datetime.now(UTC).timestamp())
        if start is not None:
            start_epoch = int(ensure_utc(start).timestamp())
        else:
            # 5 anni di history come default ragionevole
            start_epoch = end_epoch - 5 * 365 * 24 * 3600

        params = {
            "symbol": ticker,
            "resolution": resolution,
            "from": start_epoch,
            "to": end_epoch,
            "token": self._api_key,
        }
        url = f"{_BASE_URL}/stock/candle"
        with metrics.timer("fetch_latency_ms", source=self.source, kind="ohlcv_finnhub"):
            payload = await self._get_json(url, params)

        return self._normalize_candle_payload(payload, ticker)

    # ─── News sentiment (separate flow, no Pandera/persistence here) ────
    async def fetch_news_sentiment(self, ticker: str) -> NewsSentiment | None:
        """Pull aggregated news sentiment for a ticker.

        Returns ``None`` if Finnhub returns an empty payload (common for
        small caps). Sentiment is normalised to bullish/bearish percentages.
        """
        await self._rate_limiter.acquire(self._source)
        url = f"{_BASE_URL}/news-sentiment"
        params = {"symbol": ticker, "token": self._api_key}

        with metrics.timer("fetch_latency_ms", source=self.source, kind="sentiment"):
            payload = await self._get_json(url, params)

        # Schema atteso (semplificato): {sentiment:{bullishPercent, bearishPercent},
        #                                 buzz:{articlesInLastWeek}}
        sentiment_block = payload.get("sentiment") or {}
        buzz_block = payload.get("buzz") or {}
        if not sentiment_block:
            log.info("finnhub.sentiment_empty", ticker=ticker)
            return None

        return NewsSentiment(
            ticker=ticker,
            ts=datetime.now(UTC),
            bullish_pct=float(sentiment_block.get("bullishPercent", 0.0)),
            bearish_pct=float(sentiment_block.get("bearishPercent", 0.0)),
            buzz_articles=int(buzz_block.get("articlesInLastWeek", 0)),
        )

    # ─── WebSocket — gated by feature flag ──────────────────────────────
    async def stream_ticks(self, _ticker: str) -> None:
        """Real-time tick stream via Finnhub WebSocket.

        Disabled by default — enable ``realtime_websocket`` in
        ``config/feature_flags.yaml`` to use. Implementation deferred to
        Phase 7 / 8 when the analysis pipeline can consume live ticks.
        """
        if not is_enabled("realtime_websocket"):
            from shared.exceptions import FeatureDisabledError

            raise FeatureDisabledError(
                "Feature 'realtime_websocket' is disabled. "
                "Enable in config/feature_flags.yaml to stream ticks."
            )
        raise NotImplementedError(
            "WebSocket streaming will be implemented in Phase 7/8."
        )

    # ─── Internals ──────────────────────────────────────────────────────
    async def _get_json(
        self, url: str, params: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Async GET returning parsed JSON. Normalizes errors to FetchError."""
        try:
            async with (
                aiohttp.ClientSession(timeout=self._timeout) as session,
                # aiohttp accetta Mapping[str, Any]; il cast è cosmetico per mypy strict
                session.get(url, params=cast("dict[str, Any]", dict(params))) as resp,
            ):
                if resp.status in (401, 403):
                    # Mai loggare la chiave (Regola 15) — il logger comunque
                    # la redacta tramite redact_secrets in shared/logger.py
                    raise FetchError(
                        source=self._source,
                        detail=f"auth failed (HTTP {resp.status}): "
                        f"check FINNHUB_API_KEY in .env",
                    )
                if resp.status == 429:
                    raise FetchError(
                        source=self._source,
                        detail="rate limited (HTTP 429) — verify rate_limits.yaml",
                    )
                if resp.status >= 400:
                    body = await resp.text()
                    raise FetchError(
                        source=self._source,
                        detail=f"HTTP {resp.status}: {body[:200]}",
                    )
                return cast("dict[str, Any]", await resp.json())
        except aiohttp.ClientError as exc:
            metrics.inc("fetch_errors_total", source=self._source, kind="network")
            raise FetchError(
                source=self._source, detail=f"network error: {exc}"
            ) from exc

    @staticmethod
    def _normalize_candle_payload(
        payload: dict[str, Any], ticker: str
    ) -> pd.DataFrame:
        """Convert Finnhub /stock/candle response to canonical OHLCV schema.

        Finnhub returns columnar arrays:
            { "s":"ok", "t":[...], "o":[...], "h":[...], "l":[...],
              "c":[...], "v":[...] }
        Status "no_data" → empty DataFrame.
        """
        status = payload.get("s")
        if status == "no_data":
            log.info("finnhub.no_data", ticker=ticker)
            return pd.DataFrame()
        if status != "ok":
            raise FetchError(
                source="finnhub",
                detail=f"unexpected response status '{status}' for {ticker}",
            )

        timestamps = payload.get("t") or []
        if not timestamps:
            return pd.DataFrame()

        # Finnhub timestamp = epoch seconds → tz-aware UTC (Regola 19)
        ts_index = pd.to_datetime(timestamps, unit="s", utc=True)
        # pd.to_numeric su una lista restituisce np.ndarray (non Series),
        # che non ha .fillna(). Wrappiamo in pd.Series per uniformità di API
        # e per consentire fillna+astype("int64") sul volume.
        df = pd.DataFrame(
            {
                "ts": ts_index,
                "open": pd.Series(
                    pd.to_numeric(payload.get("o", []), errors="coerce")
                ).astype("float64"),
                "high": pd.Series(
                    pd.to_numeric(payload.get("h", []), errors="coerce")
                ).astype("float64"),
                "low": pd.Series(
                    pd.to_numeric(payload.get("l", []), errors="coerce")
                ).astype("float64"),
                "close": pd.Series(
                    pd.to_numeric(payload.get("c", []), errors="coerce")
                ).astype("float64"),
                "volume": pd.Series(
                    pd.to_numeric(payload.get("v", []), errors="coerce")
                )
                .fillna(0)
                .astype("int64"),
            }
        )
        # Finnhub non rilascia adj_close → usiamo close come proxy
        df["adj_close"] = df["close"]
        return df.reset_index(drop=True)
