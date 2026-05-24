"""Inflation Expectations Fetcher.

Aggrega previsioni di inflazione market-based e consumer-based via FRED:
- ``MICH``     Univ. of Michigan, 1Y consumer inflation expectation
- ``EXPINF1YR`` Cleveland Fed model-based, 1Y
- ``EXPINF3YR`` Cleveland Fed, 3Y
- ``EXPINF5YR`` Cleveland Fed, 5Y
- ``EXPINF10YR`` Cleveland Fed, 10Y
- ``T5YIE``    TIPS-implied 5Y breakeven inflation (mercato)
- ``T10YIE``   TIPS-implied 10Y breakeven inflation (mercato)

Tutte queste serie producono indicator=CPI ma con orizzonti distinti
(``1Y``/``3Y``/``5Y``/``10Y``) che non collidono con i forecast annuali Fed/CBO.
Aggiunge ricchezza al tab Dettaglio Sorgenti senza confondere il consensus.

Regola 33: zero previsioni simulate.
Regola 34: cache-first (TTL: ib_forecast = 86400s).
"""
from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx

from engine.ib_forecast.schemas import ExtractedForecast
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["InflationExpectationsFetcher"]

log = get_logger(__name__)

_TIMEOUT = 20.0
_DELAY_S = 1.0

# Catalogo serie inflazione attese.
# source distinto in ib_forecasts per ogni provider, indicator sempre CPI,
# horizon esprime la frequenza (1Y/3Y/5Y/10Y).
_FRED_SERIES: list[dict[str, str]] = [
    {"id": "MICH",        "source": "umich_consumer",     "horizon": "1Y"},
    {"id": "EXPINF1YR",   "source": "cleveland_fed",      "horizon": "1Y"},
    {"id": "EXPINF3YR",   "source": "cleveland_fed",      "horizon": "3Y"},
    {"id": "EXPINF5YR",   "source": "cleveland_fed",      "horizon": "5Y"},
    {"id": "EXPINF10YR",  "source": "cleveland_fed",      "horizon": "10Y"},
    {"id": "T5YIE",       "source": "tips_market",        "horizon": "5Y"},
    {"id": "T10YIE",      "source": "tips_market",        "horizon": "10Y"},
]

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


class InflationExpectationsFetcher:
    """Fetcher per le aspettative di inflazione consumer + market via FRED.

    Args:
        client: DuckDBClient per cache-first (Regola 34).
        fred_api_key: Override esplicito; default: ``FRED_API_KEY`` dall'env.
    """

    def __init__(self, client: DuckDBClient, fred_api_key: str = "") -> None:
        self._client = client
        self._api_key = fred_api_key or os.getenv("FRED_API_KEY", "")
        if not self._api_key:
            log.warning("inf_exp.no_api_key",
                        msg="FRED_API_KEY mancante; tutte le richieste falliranno con 400")
        self._http = httpx.Client(timeout=_TIMEOUT, headers={"Accept": "application/json"})

    def fetch_latest_projections(self) -> list[ExtractedForecast]:
        """Per ciascuna serie, ritorna l'osservazione piu' recente come forecast.

        Inflation expectations sono per natura forward-looking: il valore
        corrente rappresenta la media degli attesi sull'orizzonte indicato.
        """
        if self._is_fresh():
            log.debug("inf_exp.cache_hit")
            return self._read_from_db()

        results: list[ExtractedForecast] = []
        for meta in _FRED_SERIES:
            try:
                forecast = self._fetch_series(meta)
                if forecast is not None:
                    results.append(forecast)
                time.sleep(_DELAY_S)
            except Exception as exc:
                log.warning("inf_exp.series_failed", series=meta["id"], error=str(exc)[:100])

        if results:
            self._persist(results)
        log.info("inf_exp.done", count=len(results))
        return results

    def _fetch_series(self, meta: dict[str, str]) -> ExtractedForecast | None:
        params: dict[str, Any] = {
            "series_id": meta["id"],
            "sort_order": "desc",
            "limit": "1",
            "file_type": "json",
        }
        if self._api_key:
            params["api_key"] = self._api_key

        try:
            resp = self._http.get(_FRED_BASE, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.warning("inf_exp.http_failed", series=meta["id"], error=str(exc)[:80])
            return None

        observations = data.get("observations", [])
        if not observations:
            return None

        obs = observations[0]
        raw_val = obs.get("value", ".")
        if raw_val == "." or not raw_val:
            return None
        try:
            value = float(raw_val)
        except (ValueError, TypeError):
            return None

        obs_date = str(obs.get("date", "unknown"))
        return ExtractedForecast(
            report_id=f"infexp_{meta['id']}_{obs_date}",
            source=meta["source"],
            indicator="CPI",
            horizon=meta["horizon"],
            value=value,
            unit="percent",
            extraction_method="api",
            confidence=0.85,
            fetched_at=datetime.now(UTC),
        )

    def _is_fresh(self, ttl_s: int = 86400) -> bool:
        try:
            rows = self._client.query(
                "SELECT fetched_at FROM ib_forecasts "
                "WHERE source IN ('umich_consumer', 'cleveland_fed', 'tips_market') "
                "ORDER BY fetched_at DESC LIMIT 1"
            )
            if not rows or not rows[0][0]:
                return False
            fetched_at = rows[0][0]
            if hasattr(fetched_at, "tzinfo") and fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=UTC)
            return bool((datetime.now(UTC) - fetched_at).total_seconds() < ttl_s)
        except Exception:
            return False

    def _read_from_db(self) -> list[ExtractedForecast]:
        try:
            rows = self._client.query(
                "SELECT report_id, source, indicator, horizon, value, unit, fetched_at "
                "FROM ib_forecasts "
                "WHERE source IN ('umich_consumer', 'cleveland_fed', 'tips_market') "
                "ORDER BY fetched_at DESC LIMIT 30"
            )
            return [
                ExtractedForecast(
                    report_id=str(r[0]),
                    source=str(r[1]),
                    indicator=str(r[2]),
                    horizon=str(r[3]),
                    value=float(r[4]) if r[4] is not None else None,
                    unit=str(r[5]) if r[5] else "percent",
                    extraction_method="api",
                    confidence=0.85,
                    fetched_at=r[6],
                )
                for r in rows
            ]
        except Exception as exc:
            log.warning("inf_exp.db_read_failed", error=str(exc)[:80])
            return []

    def _persist(self, forecasts: list[ExtractedForecast]) -> None:
        for f in forecasts:
            try:
                self._client.execute(
                    "DELETE FROM ib_forecasts WHERE report_id = ?",
                    [f.report_id],
                )
                self._client.execute(
                    """
                    INSERT INTO ib_forecasts
                        (report_id, source, indicator, horizon, value, unit,
                         extraction_method, confidence, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        f.report_id, f.source, f.indicator, f.horizon,
                        f.value, f.unit, f.extraction_method,
                        f.confidence, f.fetched_at,
                    ],
                )
            except Exception as exc:
                log.warning("inf_exp.persist_failed",
                            report_id=f.report_id, error=str(exc)[:120])

    def __del__(self) -> None:
        try:
            self._http.close()
        except Exception:
            pass
