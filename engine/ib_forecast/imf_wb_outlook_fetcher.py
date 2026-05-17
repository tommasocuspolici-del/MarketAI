"""IMF World Economic Outlook + World Bank Forecasts Fetcher.

Sorgenti strutturate con 99% accuracy senza LLM.
Regola 33: zero previsioni simulate — solo API reali.
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
__all__ = ["IMFWBOutlookFetcher"]

log = get_logger(__name__)

_TIMEOUT = 30.0
_DELAY_S = 2.0

# IMF WEO API (gratuita, no key)
_IMF_BASE = "https://www.imf.org/external/datamapper/api/v1"

# World Bank API (gratuita, no key)
_WB_BASE = "https://api.worldbank.org/v2"

# Indicatori IMF da WEO per USA (ISO: US)
_IMF_INDICATORS: dict[str, dict[str, str]] = {
    "NGDP_RPCH": {"indicator": "GDP",          "source": "imf_weo"},
    "PCPIPCH":   {"indicator": "CPI",           "source": "imf_weo"},
    "LUR":       {"indicator": "UNEMPLOYMENT",  "source": "imf_weo"},
}

# Indicatori World Bank per USA
_WB_INDICATORS: dict[str, dict[str, str]] = {
    "NY.GDP.MKTP.KD.ZG":  {"indicator": "GDP",         "source": "world_bank"},
    "FP.CPI.TOTL.ZG":     {"indicator": "CPI",         "source": "world_bank"},
    "SL.UEM.TOTL.ZS":     {"indicator": "UNEMPLOYMENT", "source": "world_bank"},
}


class IMFWBOutlookFetcher:
    """Fetcher per proiezioni IMF WEO e World Bank.

    Args:
        client: DuckDBClient per cache-first (Regola 34).
    """

    def __init__(self, client: DuckDBClient) -> None:
        self._client = client
        self._http = httpx.Client(
            timeout=_TIMEOUT,
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )

    def fetch_all(self) -> list[ExtractedForecast]:
        """Scarica proiezioni da IMF e World Bank.

        Returns:
            Lista di ExtractedForecast con previsioni strutturate.
        """
        if self._is_fresh():
            log.debug("imf_wb.cache_hit")
            return self._read_from_db()

        results: list[ExtractedForecast] = []
        results.extend(self._fetch_imf())
        time.sleep(_DELAY_S)
        results.extend(self._fetch_world_bank())

        if results:
            self._persist(results)
        log.info("imf_wb.done", count=len(results))
        return results

    def _fetch_imf(self) -> list[ExtractedForecast]:
        """Scarica dati IMF WEO via API pubblica."""
        forecasts: list[ExtractedForecast] = []
        current_year = str(datetime.now(UTC).year)

        for series_id, meta in _IMF_INDICATORS.items():
            try:
                url = f"{_IMF_BASE}/{series_id}/US"
                resp = self._http.get(url, params={"periods": current_year})
                resp.raise_for_status()
                data = resp.json()

                values: dict[str, Any] = (
                    data.get("values", {})
                        .get(series_id, {})
                        .get("US", {})
                )
                val_raw = values.get(current_year)
                if val_raw is None:
                    # Tenta anno precedente come stima più recente
                    val_raw = values.get(str(int(current_year) - 1))

                if val_raw is not None:
                    forecasts.append(ExtractedForecast(
                        report_id=f"imf_weo_{series_id}_{current_year}",
                        source="imf_weo",
                        indicator=meta["indicator"],
                        horizon=current_year,
                        value=float(val_raw),
                        unit="percent",
                        extraction_method="api",
                        confidence=0.92,
                        fetched_at=datetime.now(UTC),
                    ))
                time.sleep(_DELAY_S)
            except Exception as exc:
                log.warning("imf_wb.imf_failed", series=series_id, error=str(exc)[:80])

        return forecasts

    def _fetch_world_bank(self) -> list[ExtractedForecast]:
        """Scarica dati World Bank via API pubblica."""
        forecasts: list[ExtractedForecast] = []
        current_year = datetime.now(UTC).year

        for wb_id, meta in _WB_INDICATORS.items():
            try:
                url = f"{_WB_BASE}/country/US/indicator/{wb_id}"
                resp = self._http.get(url, params={
                    "format": "json",
                    "mrv": 3,  # Most recent value: ultimi 3 anni
                    "per_page": 3,
                })
                resp.raise_for_status()
                data = resp.json()

                if not isinstance(data, list) or len(data) < 2:
                    continue

                observations: list[dict[str, Any]] = data[1] or []
                for obs in observations:
                    if obs.get("value") is None:
                        continue
                    year_str = str(obs.get("date", current_year))
                    forecasts.append(ExtractedForecast(
                        report_id=f"wb_{wb_id.replace('.', '_')}_{year_str}",
                        source="world_bank",
                        indicator=meta["indicator"],
                        horizon=year_str,
                        value=float(obs["value"]),
                        unit="percent",
                        extraction_method="api",
                        confidence=0.90,
                        fetched_at=datetime.now(UTC),
                    ))
                    break  # Solo il dato più recente per source

                time.sleep(_DELAY_S)
            except Exception as exc:
                log.warning("imf_wb.wb_failed", series=wb_id, error=str(exc)[:80])

        return forecasts

    def _is_fresh(self, ttl_s: int = 86400) -> bool:
        """Regola 34: controlla TTL prima di fetch."""
        try:
            rows = self._client.query(
                "SELECT fetched_at FROM ib_forecasts "
                "WHERE source IN ('imf_weo', 'world_bank') "
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
                "FROM ib_forecasts WHERE source IN ('imf_weo', 'world_bank') "
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
                    confidence=0.90,
                    fetched_at=r[6],
                )
                for r in rows
            ]
        except Exception as exc:
            log.warning("imf_wb.db_read_failed", error=str(exc)[:80])
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
                log.debug("imf_wb.persist_skip", error=str(exc)[:80])

    def __del__(self) -> None:
        try:
            self._http.close()
        except Exception:
            pass
