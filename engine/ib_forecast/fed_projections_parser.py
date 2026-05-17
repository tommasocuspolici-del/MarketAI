"""Fed SEP (Summary of Economic Projections) Parser.

Scarica e parsa le proiezioni FOMC dal sito Fed pubblico.
Regola 33: zero previsioni simulate — solo dati Fed reali.
Regola 34: cache-first (TTL: ib_forecast = 86400s).
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx

from engine.ib_forecast.schemas import ExtractedForecast
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["FedProjectionsParser"]

log = get_logger(__name__)

_TIMEOUT = 20.0
_DELAY_S = 1.5

# Endpoint API FRED per proiezioni FOMC (gratuito, no API key per URL pubblici)
_FRED_SERIES: dict[str, dict[str, str]] = {
    # Mediana proiezioni FOMC
    "FEDTARMD":  {"indicator": "FEDFUNDS", "horizon": "year_end", "unit": "percent"},
    "GDPC1MD":   {"indicator": "GDP",       "horizon": "year_end", "unit": "percent"},
    "PCECTPICTMD": {"indicator": "CPI",     "horizon": "year_end", "unit": "percent"},
    "UNRATEMED": {"indicator": "UNEMPLOYMENT", "horizon": "year_end", "unit": "percent"},
}

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


class FedProjectionsParser:
    """Parser per proiezioni SEP FOMC.

    Usa l'API FRED per le serie mediane FOMC (dati pubblici, no key richiesta
    per richieste non autenticate limitate).

    Args:
        client: DuckDBClient per cache-first (Regola 34).
        fred_api_key: Chiave FRED opzionale (senza key: 120 req/min).
    """

    def __init__(self, client: DuckDBClient, fred_api_key: str = "") -> None:
        self._client = client
        self._api_key = fred_api_key
        self._http = httpx.Client(timeout=_TIMEOUT, headers={"Accept": "application/json"})

    def fetch_latest_projections(self) -> list[ExtractedForecast]:
        """Scarica le ultime proiezioni FOMC disponibili.

        Returns:
            Lista di ExtractedForecast con indicatori macro FOMC.
        """
        if self._is_fresh():
            log.debug("fed_sep.cache_hit")
            return self._read_from_db()

        results: list[ExtractedForecast] = []
        for series_id, meta in _FRED_SERIES.items():
            try:
                forecast = self._fetch_series(series_id, meta)
                if forecast:
                    results.append(forecast)
                time.sleep(_DELAY_S)
            except Exception as exc:
                log.warning("fed_sep.series_failed", series=series_id, error=str(exc)[:100])

        if results:
            self._persist(results)
        log.info("fed_sep.done", count=len(results))
        return results

    def _fetch_series(self, series_id: str, meta: dict[str, str]) -> ExtractedForecast | None:
        """Scarica singola serie FRED e la converte in ExtractedForecast."""
        params: dict[str, Any] = {
            "series_id": series_id,
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
            log.warning("fed_sep.http_failed", series=series_id, error=str(exc)[:80])
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

        return ExtractedForecast(
            report_id=f"fed_sep_{series_id}_{obs.get('date', 'unknown')}",
            source="fed_sep",
            indicator=meta["indicator"],
            horizon=meta["horizon"],
            value=value,
            unit=meta["unit"],
            extraction_method="api",
            confidence=0.95,
            fetched_at=datetime.now(UTC),
        )

    def _is_fresh(self, ttl_s: int = 86400) -> bool:
        """Regola 34: controlla TTL prima di fetch."""
        try:
            rows = self._client.query(
                "SELECT fetched_at FROM ib_forecasts WHERE source='fed_sep' "
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
        """Legge previsioni recenti da DB (cache hit)."""
        try:
            rows = self._client.query(
                "SELECT report_id, source, indicator, horizon, value, unit, fetched_at "
                "FROM ib_forecasts WHERE source='fed_sep' "
                "ORDER BY fetched_at DESC LIMIT 20"
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
                    confidence=0.95,
                    fetched_at=r[6],
                )
                for r in rows
            ]
        except Exception as exc:
            log.warning("fed_sep.db_read_failed", error=str(exc)[:80])
            return []

    def _persist(self, forecasts: list[ExtractedForecast]) -> None:
        """Salva previsioni in ib_forecasts (Regola 34)."""
        for f in forecasts:
            try:
                self._client.execute(
                    """
                    INSERT INTO ib_forecasts
                        (report_id, source, indicator, horizon, value, unit,
                         extraction_method, confidence, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (report_id) DO UPDATE SET
                        value=excluded.value, fetched_at=excluded.fetched_at
                    """,
                    [
                        f.report_id, f.source, f.indicator, f.horizon,
                        f.value, f.unit, f.extraction_method,
                        f.confidence, f.fetched_at,
                    ],
                )
            except Exception as exc:
                log.debug("fed_sep.persist_skip", error=str(exc)[:80])

    def __del__(self) -> None:
        try:
            self._http.close()
        except Exception:
            pass
