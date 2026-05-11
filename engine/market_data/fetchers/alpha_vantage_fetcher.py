"""Alpha Vantage fetcher — fallback OHLCV + forex.

Alpha Vantage's free tier is severe (5 req/min, 500 req/day) — use ONLY
as a last-resort fallback when other providers are down. RateLimitManager
enforces this hard limit (configured under ``alpha_vantage`` in
``config/rate_limits.yaml``).

Endpoints used:
  · TIME_SERIES_DAILY        — OHLCV daily bars
  · TIME_SERIES_INTRADAY     — OHLCV intraday
  · FX_DAILY                 — forex daily

API key from ``ALPHA_VANTAGE_KEY`` env (Rule 15).
"""
from __future__ import annotations

import os
from collections.abc import Mapping  # noqa: TC003
from typing import TYPE_CHECKING, Any, cast

import aiohttp
import pandas as pd

from engine.market_data.fetchers.base_fetcher import BaseOhlcvFetcher
from shared.exceptions import ConfigurationError, FetchError
from shared.logger import get_logger
from shared.metrics import metrics
from shared.rate_limit_manager import RateLimitManager, get_rate_limiter
from shared.types import DataSource, TimeFrame

if TYPE_CHECKING:
    from datetime import datetime

    from engine.market_data.cleaning import DataCleaner
    from shared.db.dual_writer import DualWriter
    from shared.db.quality import QualityReportRepository

__version__ = "6.0.0"

__all__ = ["AlphaVantageFetcher"]

log = get_logger(__name__)

_BASE_URL = "https://www.alphavantage.co/query"

# Mapping TimeFrame → Alpha Vantage "function" + "interval" parameters
# Alpha Vantage richiede una "function" diversa per daily vs intraday
_DAILY_TIMEFRAMES: set[str] = {"1d"}
_INTRADAY_INTERVAL_MAP: dict[str, str] = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "60min",
}


class AlphaVantageFetcher(BaseOhlcvFetcher):
    """OHLCV + FX fallback fetcher backed by Alpha Vantage.

    Usage notes:
      · Free tier == 5 req/min: budget yourself accordingly.
      · Always cache aggressively before calling this fetcher.
      · ``fetch_fx`` is a separate method — it returns a DataFrame in the
        macro-series shape (ts, value) so it can flow through the existing
        macro pipeline if desired.
    """

    def __init__(
        self,
        rate_limiter: RateLimitManager | None = None,
        cleaner: DataCleaner | None = None,
        dual_writer: DualWriter | None = None,
        quality_repo: QualityReportRepository | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        super().__init__(
            source=DataSource.ALPHA_VANTAGE,
            rate_limiter=rate_limiter or get_rate_limiter(),
            cleaner=cleaner,
            dual_writer=dual_writer,
            quality_repo=quality_repo,
        )
        # Regola 15: API key da .env, mai hardcoded
        key = api_key or os.getenv("ALPHA_VANTAGE_KEY", "").strip()
        if not key:
            raise ConfigurationError(
                "ALPHA_VANTAGE_KEY environment variable is required."
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
        """Fetch OHLCV from Alpha Vantage. No cleaning here."""
        tf_str = timeframe.value if isinstance(timeframe, TimeFrame) else str(timeframe)

        if tf_str in _DAILY_TIMEFRAMES:
            params: dict[str, object] = {
                "function": "TIME_SERIES_DAILY_ADJUSTED",
                "symbol": ticker,
                # outputsize=full per ottenere ~20 anni di history (default=compact 100 barre)
                "outputsize": "full",
                "apikey": self._api_key,
                "datatype": "json",
            }
        elif tf_str in _INTRADAY_INTERVAL_MAP:
            params = {
                "function": "TIME_SERIES_INTRADAY",
                "symbol": ticker,
                "interval": _INTRADAY_INTERVAL_MAP[tf_str],
                "outputsize": "full",
                "apikey": self._api_key,
                "datatype": "json",
            }
        else:
            raise FetchError(
                source=self.source,
                detail=f"unsupported timeframe '{tf_str}' for Alpha Vantage",
            )

        with metrics.timer("fetch_latency_ms", source=self.source, kind="ohlcv_av"):
            payload = await self._get_json(_BASE_URL, params)

        return self._normalize_ohlcv_payload(payload, ticker, tf_str)

    # ─── FX (forex) — separate flow ─────────────────────────────────────
    async def fetch_fx(
        self,
        from_currency: str,
        to_currency: str,
    ) -> pd.DataFrame:
        """Fetch daily FX rate as a (ts, value) macro-style DataFrame.

        ``value`` is the close rate of 1 unit of ``from_currency`` in
        ``to_currency``. Useful as a fallback for ``shared/fx_service.py``.
        """
        await self._rate_limiter.acquire(self._source)
        params = {
            "function": "FX_DAILY",
            "from_symbol": from_currency,
            "to_symbol": to_currency,
            "outputsize": "compact",
            "apikey": self._api_key,
            "datatype": "json",
        }
        with metrics.timer("fetch_latency_ms", source=self.source, kind="fx"):
            payload = await self._get_json(_BASE_URL, params)

        time_series = payload.get("Time Series FX (Daily)") or {}
        if not time_series:
            log.info(
                "alpha_vantage.fx_empty",
                pair=f"{from_currency}/{to_currency}",
            )
            return pd.DataFrame()

        rows = [
            {
                "ts": pd.Timestamp(date_str, tz="UTC"),
                "value": float(values.get("4. close", "nan")),
            }
            for date_str, values in time_series.items()
        ]
        df = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
        df["value"] = pd.to_numeric(df["value"], errors="coerce").astype("float64")
        return df

    # ─── Internals ──────────────────────────────────────────────────────
    async def _get_json(
        self,
        url: str,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Async GET returning parsed JSON. Normalizes errors to FetchError."""
        try:
            async with (
                aiohttp.ClientSession(timeout=self._timeout) as session,
                # aiohttp accetta Mapping[str, Any]; il cast è cosmetico per mypy strict
                session.get(url, params=cast("dict[str, Any]", dict(params))) as resp,
            ):
                if resp.status >= 400:
                    body = await resp.text()
                    raise FetchError(
                        source=self._source,
                        detail=f"HTTP {resp.status}: {body[:200]}",
                    )
                payload = cast("dict[str, Any]", await resp.json())
                self._check_payload_for_errors(payload)
                return payload
        except aiohttp.ClientError as exc:
            metrics.inc("fetch_errors_total", source=self._source, kind="network")
            raise FetchError(
                source=self._source, detail=f"network error: {exc}"
            ) from exc

    def _check_payload_for_errors(self, payload: dict[str, Any]) -> None:
        """Alpha Vantage often returns 200 OK with a JSON error message."""
        # Alpha Vantage segnala errori semantici (rate limit, invalid key)
        # con una chiave "Error Message" o "Note" nel payload, mantenendo
        # comunque HTTP 200 — quindi va ispezionato il body
        if "Error Message" in payload:
            raise FetchError(
                source=self._source, detail=str(payload["Error Message"])[:200]
            )
        # "Note" è il messaggio di rate-limit di Alpha Vantage
        if "Note" in payload:
            raise FetchError(
                source=self._source,
                detail=f"rate limited or quota exceeded: {str(payload['Note'])[:200]}",
            )
        # "Information" usato per messaggi di throttling più recenti
        if "Information" in payload and not any(
            k.startswith("Time Series") or k.startswith("Meta") for k in payload
        ):
            raise FetchError(
                source=self._source,
                detail=f"info-only response: {str(payload['Information'])[:200]}",
            )

    @staticmethod
    def _normalize_ohlcv_payload(
        payload: dict[str, Any], ticker: str, tf_str: str
    ) -> pd.DataFrame:
        """Convert Alpha Vantage time-series JSON to canonical OHLCV schema."""
        # Identifica la chiave delle barre: nome cambia per daily/intraday/adjusted
        ts_key = next(
            (k for k in payload if k.startswith("Time Series")),
            None,
        )
        if ts_key is None:
            log.info("alpha_vantage.no_timeseries_key", ticker=ticker, keys=list(payload))
            return pd.DataFrame()

        bars: dict[str, dict[str, str]] = payload[ts_key]
        if not bars:
            return pd.DataFrame()

        # Alpha Vantage usa naming variabile: "1. open" daily, "5. adjusted close" only on adjusted
        rows: list[dict[str, object]] = []
        for ts_str, values in bars.items():
            row = {
                "ts": pd.Timestamp(ts_str, tz="UTC"),
                "open": float(values.get("1. open", "nan")),
                "high": float(values.get("2. high", "nan")),
                "low": float(values.get("3. low", "nan")),
                "close": float(values.get("4. close", "nan")),
                "volume": int(float(values.get("6. volume", values.get("5. volume", "0")))),
            }
            # adj_close presente solo nelle TIME_SERIES_DAILY_ADJUSTED
            adj = values.get("5. adjusted close")
            if adj is not None:
                row["adj_close"] = float(adj)
            rows.append(row)

        df = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
        # Tipi espliciti per coerenza con OHLCV_SCHEMA (Regola 9)
        for col in ("open", "high", "low", "close", "adj_close"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
        df["volume"] = df["volume"].astype("int64")
        return df
