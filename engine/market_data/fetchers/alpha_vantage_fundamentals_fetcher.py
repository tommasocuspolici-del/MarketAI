"""Alpha Vantage Fundamentals Fetcher — valuation ratios + income/balance data.

Extends the existing ``AlphaVantageFetcher`` (OHLCV/FX) with fundamentals
endpoints. This module is intentionally separate (Regola 2 — SRP) because:
  · cadenza diversa: settimanale vs giornaliera per i prezzi
  · schema output diverso: fundamentals_valuation, non prices_ohlcv
  · feature flag diverso: alpha_vantage_premium (Regola 29)

Endpoints usati:
  · OVERVIEW       — P/E, P/B, EV/EBITDA, beta, dividend yield, market cap
  · INCOME_STATEMENT — EPS e revenue quarterly (ultimi 4 quarter)
  · BALANCE_SHEET  — assets, debt, equity quarterly (ultimi 4 quarter)

Rate limit AV free tier: 5 req/min, 500 req/day (Regola 28).
API key: ALPHA_VANTAGE_KEY da .env (Regola 15).
Feature flag: alpha_vantage_premium (Regola 29).

ANTI-REGRESSIONE (v9.0 — Settimana 1 Roadmap v3.0):
  · _check_payload_for_errors() DEVE essere chiamato su ogni risposta AV:
    AV restituisce HTTP 200 anche su errori semantici (rate limit, invalid key).
  · Non usare AlphaVantageFetcher direttamente — questo modulo ha le sue
    sessioni aiohttp (timeout diverso, endpoint diversi).
"""
from __future__ import annotations

import os
from typing import Any, cast

import aiohttp
import numpy as np
import pandas as pd

from shared.exceptions import ConfigurationError, FetchError, FeatureDisabledError
from shared.feature_flags import is_enabled
from shared.logger import get_logger
from shared.metrics import metrics
from shared.rate_limit_manager import RateLimitManager, get_rate_limiter
from shared.types import DataSource

__version__ = "9.0.0"
__all__ = ["AlphaVantageFundamentalsFetcher"]

log = get_logger(__name__)

_BASE_URL = "https://www.alphavantage.co/query"
# Timeout più alto dei prezzi: le risposte AV OVERVIEW possono essere lente
_DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=120.0)

# Campi OVERVIEW da estrarre e relativo tipo atteso
# Tupla: (campo_av, colonna_output, conversione_numpy)
_OVERVIEW_FIELDS: list[tuple[str, str, type]] = [
    ("PERatio", "pe_ttm", float),
    ("ForwardPE", "pe_forward", float),
    ("PriceToBookRatio", "pb", float),
    ("PriceToSalesRatioTTM", "ps", float),
    ("EVToEBITDA", "ev_ebitda", float),
    ("DividendYield", "dividend_yield", float),
    ("PayoutRatio", "payout_ratio", float),
    ("Beta", "beta", float),
    ("MarketCapitalization", "market_cap", float),
]


class AlphaVantageFundamentalsFetcher:
    """Fetches valuation + fundamental data from Alpha Vantage API.

    Feature-flag gated: richiede ``alpha_vantage_premium: true`` in
    config/feature_flags.yaml (Regola 29).

    Tutti i calcoli numerici usano numpy.float64 (Regola 8).
    Regola 12: ogni metodo pubblico segue fetch → clean → validate → return.
    """

    def __init__(
        self,
        rate_limiter: RateLimitManager | None = None,
        api_key: str | None = None,
    ) -> None:
        # REGOLA 29: verifica feature flag all'istanziazione, non solo al call
        # Evita che il fetcher venga costruito in ambienti di test senza flag.
        # (La verifica è ripetuta in fetch_valuation per sicurezza difensiva.)
        if not is_enabled("alpha_vantage_premium"):
            raise FeatureDisabledError(
                "Feature 'alpha_vantage_premium' is disabled. "
                "Enable in config/feature_flags.yaml and provide a valid AV key."
            )

        # REGOLA 15: API key da .env, mai hardcoded
        key = api_key or os.getenv("ALPHA_VANTAGE_KEY", "").strip()
        if not key:
            raise ConfigurationError(
                "ALPHA_VANTAGE_KEY environment variable is required for "
                "AlphaVantageFundamentalsFetcher."
            )
        self._api_key: str = key
        self._rate_limiter = rate_limiter or get_rate_limiter()
        self._source = DataSource.ALPHA_VANTAGE.value

    # ─── Public API ──────────────────────────────────────────────────────────

    async def fetch_valuation(self, ticker: str) -> pd.DataFrame:
        """Fetch valuation ratios for a single ticker from AV OVERVIEW.

        Args:
            ticker: Equity ticker (e.g. 'AAPL', 'MSFT').

        Returns:
            Single-row DataFrame matching ``fundamentals_valuation`` schema:
              ticker, computed_at, pe_ttm, pe_forward, pb, ps, ev_ebitda,
              dividend_yield, payout_ratio, beta, market_cap, source.
            Returns empty DataFrame on error (graceful degradation).

        Raises:
            FetchError: On network or API errors.
            FeatureDisabledError: If flag was disabled after __init__.
        """
        # Verifica difensiva del feature flag (potrebbe essere cambiato a runtime)
        if not is_enabled("alpha_vantage_premium"):
            raise FeatureDisabledError("alpha_vantage_premium is disabled")

        await self._rate_limiter.acquire(self._source)

        params = {
            "function": "OVERVIEW",
            "symbol": ticker,
            "apikey": self._api_key,
        }
        with metrics.timer("fetch_latency_ms", source=self._source, kind="overview"):
            payload = await self._get_json(params)

        if not payload or "Symbol" not in payload:
            log.info("av_fundamentals.overview_empty", ticker=ticker)
            return pd.DataFrame()

        return self._normalize_overview(ticker, payload)

    async def fetch_income_statement(
        self, ticker: str, limit_quarters: int = 4
    ) -> pd.DataFrame:
        """Fetch quarterly income statement (EPS + revenue).

        Args:
            ticker: Equity ticker.
            limit_quarters: Number of quarters to return (default 4 = 1 year).

        Returns:
            DataFrame with columns: ticker, report_date, period,
              revenue, net_income, eps_diluted.
        """
        if not is_enabled("alpha_vantage_premium"):
            raise FeatureDisabledError("alpha_vantage_premium is disabled")

        await self._rate_limiter.acquire(self._source)

        params = {
            "function": "INCOME_STATEMENT",
            "symbol": ticker,
            "apikey": self._api_key,
        }
        with metrics.timer("fetch_latency_ms", source=self._source, kind="income_statement"):
            payload = await self._get_json(params)

        quarterly = payload.get("quarterlyReports", [])[:limit_quarters]
        if not quarterly:
            return pd.DataFrame()

        return self._normalize_income(ticker, quarterly)

    async def fetch_balance_sheet(
        self, ticker: str, limit_quarters: int = 4
    ) -> pd.DataFrame:
        """Fetch quarterly balance sheet (assets, debt, equity).

        Args:
            ticker: Equity ticker.
            limit_quarters: Number of quarters to return (default 4 = 1 year).

        Returns:
            DataFrame with columns: ticker, report_date, period,
              total_assets, total_debt, equity.
        """
        if not is_enabled("alpha_vantage_premium"):
            raise FeatureDisabledError("alpha_vantage_premium is disabled")

        await self._rate_limiter.acquire(self._source)

        params = {
            "function": "BALANCE_SHEET",
            "symbol": ticker,
            "apikey": self._api_key,
        }
        with metrics.timer("fetch_latency_ms", source=self._source, kind="balance_sheet"):
            payload = await self._get_json(params)

        quarterly = payload.get("quarterlyReports", [])[:limit_quarters]
        if not quarterly:
            return pd.DataFrame()

        return self._normalize_balance(ticker, quarterly)

    # ─── Normalizzatori ───────────────────────────────────────────────────────

    def _normalize_overview(
        self, ticker: str, payload: dict[str, Any]
    ) -> pd.DataFrame:
        """Extract valuation fields from OVERVIEW payload into a single-row DataFrame."""
        row: dict[str, object] = {
            "ticker": ticker,
            # UTC timestamp del calcolo (Regola 19: nessuna data naive)
            "computed_at": pd.Timestamp.now(tz="UTC"),
            "source": "alpha_vantage",
        }

        for av_field, col, _ in _OVERVIEW_FIELDS:
            raw = payload.get(av_field, "None")
            # AV restituisce "None" (stringa) o valore numerico come stringa
            if raw in ("None", "", "-", None):
                row[col] = np.nan
            else:
                try:
                    # float64 per conformità Regola 8
                    row[col] = np.float64(raw)
                except (ValueError, TypeError):
                    log.debug(
                        "av_fundamentals.overview_parse_error",
                        ticker=ticker,
                        field=av_field,
                        raw=raw,
                    )
                    row[col] = np.nan

        df = pd.DataFrame([row])
        # Cast esplicito float64 su tutte le colonne numeriche
        numeric_cols = [col for _, col, _ in _OVERVIEW_FIELDS]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
        return df

    @staticmethod
    def _normalize_income(
        ticker: str, reports: list[dict[str, Any]]
    ) -> pd.DataFrame:
        """Normalize AV quarterly income statement reports."""

        def _safe_float(val: object) -> float:
            if val in (None, "None", "", "-"):
                return float(np.nan)
            try:
                return float(np.float64(val))  # type: ignore[arg-type]
            except (ValueError, TypeError):
                return float(np.nan)

        rows: list[dict[str, object]] = []
        for r in reports:
            report_date = pd.Timestamp(str(r.get("fiscalDateEnding", "")), tz="UTC")
            rows.append({
                "ticker": ticker,
                "report_date": report_date,
                "period": "Q",  # AV non separa Q1/Q2/Q3/Q4 nei quarterly
                "revenue": _safe_float(r.get("totalRevenue")),
                "gross_profit": _safe_float(r.get("grossProfit")),
                "ebit": _safe_float(r.get("operatingIncome")),
                "net_income": _safe_float(r.get("netIncome")),
                "eps_diluted": _safe_float(r.get("reportedEPS")),
                "source": "alpha_vantage",
            })

        df = pd.DataFrame(rows)
        for col in ("revenue", "gross_profit", "ebit", "net_income", "eps_diluted"):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
        return df

    @staticmethod
    def _normalize_balance(
        ticker: str, reports: list[dict[str, Any]]
    ) -> pd.DataFrame:
        """Normalize AV quarterly balance sheet reports."""

        def _safe_float(val: object) -> float:
            if val in (None, "None", "", "-"):
                return float(np.nan)
            try:
                return float(np.float64(val))  # type: ignore[arg-type]
            except (ValueError, TypeError):
                return float(np.nan)

        rows: list[dict[str, object]] = []
        for r in reports:
            report_date = pd.Timestamp(str(r.get("fiscalDateEnding", "")), tz="UTC")

            # Debito totale: LT + current; usa quello disponibile
            lt = _safe_float(r.get("longTermDebt"))
            st = _safe_float(r.get("currentDebt"))
            if not np.isnan(lt) and not np.isnan(st):
                total_debt: float = lt + st
            elif not np.isnan(lt):
                total_debt = lt
            elif not np.isnan(st):
                total_debt = st
            else:
                total_debt = float(np.nan)

            rows.append({
                "ticker": ticker,
                "report_date": report_date,
                "period": "Q",
                "total_assets": _safe_float(r.get("totalAssets")),
                "total_debt": total_debt,
                "equity": _safe_float(r.get("totalShareholderEquity")),
                "source": "alpha_vantage",
            })

        df = pd.DataFrame(rows)
        for col in ("total_assets", "total_debt", "equity"):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
        return df

    # ─── HTTP helper ─────────────────────────────────────────────────────────

    async def _get_json(self, params: dict[str, str]) -> dict[str, Any]:
        """Async GET returning parsed JSON with AV error normalization.

        ANTI-REGRESSIONE: _check_payload_for_errors() è OBBLIGATORIO qui.
        Alpha Vantage restituisce HTTP 200 anche su rate limit / key invalida.
        Questo errore si è già presentato nel fetcher base (v6.x) — non
        rimuovere il check anche se i test sembrano passare senza.
        """
        try:
            async with (
                aiohttp.ClientSession(timeout=_DEFAULT_TIMEOUT) as session,
                session.get(_BASE_URL, params=params) as resp,
            ):
                if resp.status >= 400:
                    body = await resp.text()
                    raise FetchError(
                        source=self._source,
                        detail=f"HTTP {resp.status}: {body[:200]}",
                    )
                payload = cast("dict[str, Any]", await resp.json())
                # CRITICO: AV invia errori come JSON con HTTP 200
                self._check_payload_for_errors(payload)
                return payload
        except aiohttp.ClientError as exc:
            metrics.inc("fetch_errors_total", source=self._source, kind="network")
            raise FetchError(
                source=self._source, detail=f"network error: {exc}"
            ) from exc

    def _check_payload_for_errors(self, payload: dict[str, Any]) -> None:
        """Detect AV error bodies (HTTP 200 but semantic error).

        ANTI-REGRESSIONE: questo metodo deve restare identico al metodo
        omonimo in AlphaVantageFetcher. Se AV cambia i nomi dei campi
        di errore, aggiornare ENTRAMBI i file.
        """
        if "Error Message" in payload:
            raise FetchError(
                source=self._source, detail=str(payload["Error Message"])[:200]
            )
        if "Note" in payload:
            raise FetchError(
                source=self._source,
                detail=f"rate limited: {str(payload['Note'])[:200]}",
            )
        if "Information" in payload and not any(
            k.startswith(("Time Series", "Meta", "Quarterly", "Annual", "Symbol"))
            for k in payload
        ):
            raise FetchError(
                source=self._source,
                detail=f"info-only response: {str(payload['Information'])[:200]}",
            )
