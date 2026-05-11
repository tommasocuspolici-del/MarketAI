"""SEC EDGAR fundamentals fetcher.

SEC exposes a structured JSON facts API that returns all reported XBRL
facts for a given CIK (Central Index Key) — much cleaner than parsing
10-K/10-Q HTML filings. We use ``aiohttp`` directly (Rule 11).

Endpoints:
  · https://data.sec.gov/submissions/CIK{cik:010d}.json   (filings index)
  · https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json   (all facts)

The SEC explicitly requires a User-Agent identifying the user — without
it, requests are throttled / banned. We read ``SEC_EDGAR_USER_AGENT`` from
``.env`` (Rule 15). Rate limit configured under ``sec_edgar`` in
``config/rate_limits.yaml`` (Rule 28).

Bulk download is feature-flag gated (``edgar_bulk_download`` — Rule 29).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import aiohttp
import pandas as pd

from shared.exceptions import ConfigurationError, FetchError
from shared.feature_flags import is_enabled
from shared.logger import get_logger
from shared.metrics import metrics
from shared.rate_limit_manager import RateLimitManager, get_rate_limiter
from shared.types import DataSource

if TYPE_CHECKING:
    from datetime import datetime
    pass

__version__ = "6.0.0"

__all__ = ["EdgarFact", "SECEdgarFetcher"]

log = get_logger(__name__)

_BASE_URL = "https://data.sec.gov"
_FACTS_PATH = "/api/xbrl/companyfacts/CIK{cik:010d}.json"
_SUBMISSIONS_PATH = "/submissions/CIK{cik:010d}.json"


@dataclass(frozen=True, slots=True)
class EdgarFact:
    """A single fundamental fact reported in an SEC filing."""

    ticker: str
    cik: str
    metric: str           # GAAP concept (e.g. "Revenues", "NetIncomeLoss")
    period_end: datetime
    period_type: str      # "Q1" | "Q2" | "Q3" | "Q4" | "FY"
    value: float
    currency: str
    filing_date: datetime
    form_type: str        # "10-K", "10-Q", ...


class SECEdgarFetcher:
    """Fetches XBRL facts from the SEC EDGAR JSON API.

    Unlike OHLCV / macro fetchers this returns a list of ``EdgarFact``
    objects rather than a single DataFrame, because the natural shape
    of fundamentals is per-(metric, period_end) and persistence happens
    on the dedicated ``fundamentals`` DuckDB table.
    """

    def __init__(
        self,
        rate_limiter: RateLimitManager | None = None,
        user_agent: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        # Regola 15: User-Agent obbligatorio per SEC, da .env
        ua = user_agent or os.getenv("SEC_EDGAR_USER_AGENT", "").strip()
        if not ua:
            raise ConfigurationError(
                "SEC_EDGAR_USER_AGENT environment variable is required. "
                "Format: 'Your Name your_email@example.com'"
            )
        self._user_agent: str = ua
        self._rate_limiter = rate_limiter or get_rate_limiter()
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._source = DataSource.SEC_EDGAR.value

    # ─── Public API ──────────────────────────────────────────────────────
    async def fetch_company_facts(
        self,
        ticker: str,
        cik: str,
        metrics_filter: list[str] | None = None,
    ) -> list[EdgarFact]:
        """Download all XBRL facts for a CIK and convert them to EdgarFact list.

        Args:
            ticker: User-facing symbol (used to label the facts).
            cik: Central Index Key as zero-padded string or plain integer.
            metrics_filter: If provided, only keep facts whose GAAP concept
                appears in this list. Otherwise, return everything.

        Raises:
            FetchError: On network / parse errors.
        """
        cik_int = int(cik.lstrip("0") or "0")
        await self._rate_limiter.acquire(self._source)

        url = _BASE_URL + _FACTS_PATH.format(cik=cik_int)
        with metrics.timer("fetch_latency_ms", source=self._source, kind="facts"):
            payload = await self._get_json(url)

        return self._parse_facts(ticker, cik_int, payload, metrics_filter)

    async def fetch_filings_index(self, cik: str) -> dict[str, Any]:
        """Return the filings index JSON (list of recent filings)."""
        cik_int = int(cik.lstrip("0") or "0")
        await self._rate_limiter.acquire(self._source)
        url = _BASE_URL + _SUBMISSIONS_PATH.format(cik=cik_int)
        return await self._get_json(url)

    async def bulk_download(
        self,
        ticker_to_cik: dict[str, str],
        metrics_filter: list[str] | None = None,
    ) -> dict[str, list[EdgarFact]]:
        """Download facts for many tickers (gated by feature flag).

        Args:
            ticker_to_cik: Mapping of ticker → CIK string.
            metrics_filter: Optional GAAP concepts whitelist.

        Returns:
            ``{ticker: [EdgarFact, ...]}`` for every ticker successfully fetched.
            Tickers that fail are logged and SKIPPED (partial success allowed).

        Raises:
            FeatureDisabledError: If ``edgar_bulk_download`` is off (Rule 29).
        """
        if not is_enabled("edgar_bulk_download"):
            from shared.exceptions import FeatureDisabledError

            raise FeatureDisabledError(
                "Feature 'edgar_bulk_download' is disabled. "
                "Enable in config/feature_flags.yaml to run bulk imports."
            )

        results: dict[str, list[EdgarFact]] = {}
        for ticker, cik in ticker_to_cik.items():
            try:
                results[ticker] = await self.fetch_company_facts(
                    ticker, cik, metrics_filter
                )
                log.info(
                    "edgar.bulk_progress", ticker=ticker, facts=len(results[ticker])
                )
            except FetchError as exc:
                log.warning("edgar.bulk_skip", ticker=ticker, error=str(exc))
                continue
        return results

    # ─── Persistence helper ─────────────────────────────────────────────
    @staticmethod
    def to_dataframe(facts: list[EdgarFact]) -> pd.DataFrame:
        """Convert a list of EdgarFact to a DataFrame matching `fundamentals` table."""
        if not facts:
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "ticker": f.ticker,
                    "cik": str(f.cik),
                    "metric": f.metric,
                    "period_end": f.period_end,
                    "period_type": f.period_type,
                    "value": f.value,
                    "currency": f.currency,
                    "filing_date": f.filing_date,
                    "form_type": f.form_type,
                    "source": "sec_edgar",
                }
                for f in facts
            ]
        )

    # ─── Internals ──────────────────────────────────────────────────────
    async def _get_json(self, url: str) -> dict[str, Any]:
        """GET a JSON resource with the SEC-required headers."""
        headers = {
            "User-Agent": self._user_agent,
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            # SEC accetta solo connessioni HTTPS verso data.sec.gov
        }
        try:
            async with (
                aiohttp.ClientSession(timeout=self._timeout) as session,
                session.get(url, headers=headers) as resp,
            ):
                if resp.status == 404:
                    raise FetchError(
                        source=self._source,
                        detail=f"CIK not found at {url}",
                    )
                if resp.status >= 400:
                    body = await resp.text()
                    raise FetchError(
                        source=self._source,
                        detail=f"HTTP {resp.status} from SEC: {body[:200]}",
                    )
                # cast esplicito: resp.json() restituisce Any → mypy strict
                return cast("dict[str, Any]", await resp.json())
        except aiohttp.ClientError as exc:
            metrics.inc("fetch_errors_total", source=self._source, kind="network")
            raise FetchError(
                source=self._source, detail=f"network error: {exc}"
            ) from exc

    def _parse_facts(
        self,
        ticker: str,
        cik: int,
        payload: dict[str, Any],
        metrics_filter: list[str] | None,
    ) -> list[EdgarFact]:
        """Walk the EDGAR ``companyfacts`` JSON and emit EdgarFact objects.

        Structure of ``payload``:
            {
              "cik": int,
              "facts": {
                "us-gaap": {
                  "Revenues": {
                    "units": {
                      "USD": [
                        {"end":"2024-12-31","val":...,"fy":2024,"fp":"FY",
                         "form":"10-K","filed":"2025-02-14", ...},
                        ...
                      ]
                    }
                  },
                  ...
                }
              }
            }
        """
        out: list[EdgarFact] = []
        gaap = payload.get("facts", {}).get("us-gaap", {})

        allowed = {m.lower() for m in metrics_filter} if metrics_filter else None

        for metric_name, metric_data in gaap.items():
            if allowed is not None and metric_name.lower() not in allowed:
                continue
            units_block = metric_data.get("units", {})
            # Ogni metrica può avere più unità (USD, shares, ratio…). Le iteriamo
            # tutte, conservando l'unità come "currency" anche se non monetaria.
            for unit_name, observations in units_block.items():
                for obs in observations:
                    fact = self._build_fact(
                        ticker=ticker,
                        cik=cik,
                        metric=metric_name,
                        unit=unit_name,
                        obs=obs,
                    )
                    if fact is not None:
                        out.append(fact)
        return out

    @staticmethod
    def _build_fact(
        ticker: str,
        cik: int,
        metric: str,
        unit: str,
        obs: dict[str, Any],
    ) -> EdgarFact | None:
        """Convert a single XBRL observation dict to an EdgarFact, or None on error."""
        try:
            period_end = pd.to_datetime(obs["end"], utc=True).to_pydatetime()
            filing_date = pd.to_datetime(obs.get("filed", obs["end"]), utc=True).to_pydatetime()
            return EdgarFact(
                ticker=ticker,
                cik=str(cik),
                metric=metric,
                period_end=period_end,
                period_type=str(obs.get("fp", "FY")),
                value=float(obs["val"]),
                currency=unit,
                filing_date=filing_date,
                form_type=str(obs.get("form", "")),
            )
        except (KeyError, ValueError, TypeError) as exc:
            # Skip osservazioni malformate senza far cadere l'intero parsing
            log.debug("edgar.malformed_obs", metric=metric, error=str(exc))
            return None
