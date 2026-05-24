"""Fed SEP (Summary of Economic Projections) Parser.

Scarica e parsa le proiezioni FOMC dal sito Fed pubblico.
Regola 33: zero previsioni simulate — solo dati Fed reali.
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
from shared.resilience.error_policy import error_policy, ErrorLevel

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.1.0"
__all__ = ["FedProjectionsParser"]

log = get_logger(__name__)

_TIMEOUT = 20.0
_DELAY_S = 1.5

# FRED SEP (Summary of Economic Projections) — serie mediane FOMC.
# Convenzione FRED: <INDICATOR>MD per la mediana annuale (una osservazione per
# anno target), <INDICATOR>MDLR per "Longer Run". Tutte richiedono FRED_API_KEY.
_FRED_SERIES: dict[str, dict[str, str]] = {
    "FEDTARMD":    {"indicator": "FEDFUNDS",     "horizon": "year_end", "unit": "percent"},
    "FEDTARMDLR":  {"indicator": "FEDFUNDS",     "horizon": "longer_run", "unit": "percent"},
    "GDPC1MD":     {"indicator": "GDP",          "horizon": "year_end", "unit": "percent"},
    "GDPC1MDLR":   {"indicator": "GDP",          "horizon": "longer_run", "unit": "percent"},
    "PCECTPIMD":   {"indicator": "CPI",          "horizon": "year_end", "unit": "percent"},
    "PCECTPIMDLR": {"indicator": "CPI",          "horizon": "longer_run", "unit": "percent"},
    "UNRATEMD":    {"indicator": "UNEMPLOYMENT", "horizon": "year_end", "unit": "percent"},
    "UNRATEMDLR":  {"indicator": "UNEMPLOYMENT", "horizon": "longer_run", "unit": "percent"},
    "JCXFEMD":     {"indicator": "COREPCE",      "horizon": "year_end", "unit": "percent"},
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
        # FRED richiede sempre api_key per le serie SEP; usa env se non passata.
        self._api_key = fred_api_key or os.getenv("FRED_API_KEY", "")
        if not self._api_key:
            log.warning("fed_sep.no_api_key",
                        msg="FRED_API_KEY mancante; tutte le richieste falliranno con 400")
        self._http = httpx.Client(timeout=_TIMEOUT, headers={"Accept": "application/json"})

    def fetch_latest_projections(self) -> list[ExtractedForecast]:
        """Scarica le ultime proiezioni FOMC disponibili.

        Per le serie annuali (es. ``GDPC1MD``) FRED espone una osservazione per
        ogni anno target del SEP corrente (es. 2026, 2027, 2028). Ricava un
        ExtractedForecast per ogni anno futuro disponibile. Per le serie
        ``Longer Run`` l'horizon viene impostato a ``"longer_run"``.

        Returns:
            Lista di ExtractedForecast con indicatori macro FOMC.
        """
        if self._is_fresh():
            log.debug("fed_sep.cache_hit")
            return self._read_from_db()

        results: list[ExtractedForecast] = []
        for series_id, meta in _FRED_SERIES.items():
            try:
                results.extend(self._fetch_series(series_id, meta))
                time.sleep(_DELAY_S)
            except Exception as exc:
                log.warning("fed_sep.series_failed", series=series_id, error=str(exc)[:100])

        if results:
            self._persist(results)
        log.info("fed_sep.done", count=len(results))
        return results

    def _fetch_series(self, series_id: str, meta: dict[str, str]) -> list[ExtractedForecast]:
        """Scarica singola serie FRED e ritorna una forecast per ogni anno target.

        Per ``longer_run`` ritorna una singola forecast (osservazione più recente).
        Per ``year_end`` ritorna una forecast per ogni anno >= anno corrente.
        """
        params: dict[str, Any] = {
            "series_id": series_id,
            "sort_order": "asc",
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
            return []

        observations = data.get("observations", [])
        if not observations:
            return []

        is_longer_run = meta["horizon"] == "longer_run"
        current_year = datetime.now(UTC).year
        forecasts: list[ExtractedForecast] = []

        # Per Longer Run: prendi l'osservazione più recente.
        # Per year_end: prendi tutte le osservazioni con anno >= current_year.
        relevant = ([observations[-1]] if is_longer_run else
                    [o for o in observations
                     if self._obs_year(o) is not None
                     and self._obs_year(o) >= current_year])

        for obs in relevant:
            raw_val = obs.get("value", ".")
            if raw_val == "." or not raw_val:
                continue
            try:
                value = float(raw_val)
            except (ValueError, TypeError):
                continue
            obs_date = str(obs.get("date", "unknown"))
            horizon = "longer_run" if is_longer_run else obs_date[:4]
            forecasts.append(ExtractedForecast(
                report_id=f"fed_sep_{series_id}_{obs_date}",
                source="fed_sep",
                indicator=meta["indicator"],
                horizon=horizon,
                value=value,
                unit=meta["unit"],
                extraction_method="api",
                confidence=0.95,
                fetched_at=datetime.now(UTC),
            ))
        return forecasts

    @staticmethod
    def _obs_year(obs: dict[str, Any]) -> int | None:
        try:
            return int(str(obs.get("date", ""))[:4])
        except (ValueError, TypeError):
            return None

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
        """Salva previsioni in ib_forecasts (Regola 34).

        Pattern delete-then-insert: la PK è ``forecast_id`` (UUID auto), quindi
        ``ON CONFLICT (report_id)`` non è applicabile.
        """
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
                log.warning("fed_sep.persist_failed",
                            report_id=f.report_id, error=str(exc)[:120])

    def __del__(self) -> None:
        try:
            self._http.close()
        except Exception as exc:
            error_policy.handle(exc, level=ErrorLevel.RECOVER, context="fed_projections_parser", fallback=None)
