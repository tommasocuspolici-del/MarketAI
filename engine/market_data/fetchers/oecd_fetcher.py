"""OECD Stats API Fetcher — Leading Indicators, CLI, Main Economic Indicators.

Sorgente: https://stats.oecd.org/SDMX-JSON/data/
Gratuito, unlimited (throttling soft). Nessuna API key richiesta.
Regola 33: zero dati hardcoded.
Regola 34: cache-first (TTL: macro_oecd = 86400s).
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
import pandas as pd

from shared.exceptions import FetchError
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["OECDFetcher"]

log = get_logger(__name__)

_BASE_URL = "https://stats.oecd.org/SDMX-JSON/data"
_TIMEOUT = 30.0
_DELAY_S = 1.0  # Throttling leggero

# Serie OECD principali
OECD_SERIES: dict[str, dict[str, str]] = {
    # Composite Leading Indicators
    "MEI_CLI/LOLITOAA.USA+GBR+DEU+JPN+CHN+FRA+ITA+OECDE.M": {
        "name": "CLI Leading Indicator (amplitude adjusted)",
        "series_prefix": "OECD_CLI",
    },
    # Business Confidence
    "MEI/BSCICP03.USA+DEU+GBR+JPN+FRA+ITA.M": {
        "name": "Business Confidence Index",
        "series_prefix": "OECD_BCI",
    },
    # Consumer Confidence
    "MEI/CSCICP03.USA+DEU+GBR+JPN+FRA+ITA.M": {
        "name": "Consumer Confidence Index",
        "series_prefix": "OECD_CCI",
    },
}

# Paesi supportati
OECD_COUNTRIES = ["USA", "GBR", "DEU", "JPN", "CHN", "FRA", "ITA", "OECDE"]


class OECDFetcher:
    """Fetcher per Leading Indicators, Business/Consumer Confidence OECD.

    Args:
        client: DuckDBClient per persistenza cache-first (Regola 34).

    Usage::

        fetcher = OECDFetcher(client=get_duckdb_client())
        df = fetcher.fetch_leading_indicators()
    """

    def __init__(self, client: DuckDBClient) -> None:
        self._client = client
        self._http = httpx.Client(
            timeout=_TIMEOUT,
            headers={"Accept": "application/json"},
        )

    def fetch_series(self, dataset_key: str, start_period: str = "2010-01") -> pd.DataFrame:
        """Scarica una serie OECD.

        Args:
            dataset_key:  Chiave SDMX OECD (es. 'MEI_CLI/LOLITOAA.USA...').
            start_period: YYYY-MM di inizio.

        Returns:
            DataFrame con colonne: series_id, series_date, value, country, source.
        """
        meta = OECD_SERIES.get(dataset_key, {
            "name": dataset_key,
            "series_prefix": "OECD_CUSTOM",
        })
        url = f"{_BASE_URL}/{dataset_key}"

        log.info("oecd_fetcher.fetch", dataset=dataset_key, name=meta["name"])
        try:
            time.sleep(_DELAY_S)
            resp = self._http.get(url, params={
                "startTime": start_period,
                "endTime": datetime.now(UTC).strftime("%Y-%m"),
                "contentType": "application/json",
            })
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise FetchError(source="oecd", detail=f"HTTP {exc.response.status_code}") from exc
        except Exception as exc:
            raise FetchError(source="oecd", detail=str(exc)) from exc

        rows = self._parse(data, meta["series_prefix"])
        if not rows:
            log.warning("oecd_fetcher.empty_response", dataset=dataset_key)
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        self._persist(df)
        log.info("oecd_fetcher.done", dataset=dataset_key, rows=len(df))
        return df

    def fetch_leading_indicators(self) -> dict[str, pd.DataFrame]:
        """Scarica tutti i CLI e confidence index configurati."""
        results: dict[str, pd.DataFrame] = {}
        for key, meta in OECD_SERIES.items():
            try:
                df = self.fetch_series(key)
                results[meta["series_prefix"]] = df
            except FetchError as exc:
                log.warning("oecd_fetcher.series_failed", dataset=key, error=str(exc))
        return results

    def _parse(self, data: dict[str, Any], series_prefix: str) -> list[dict[str, Any]]:
        """Estrae osservazioni da risposta SDMX-JSON OECD."""
        rows: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        try:
            datasets = data.get("dataSets", [])
            if not datasets:
                return rows

            structure = data.get("structure", {})
            dims_obs = structure.get("dimensions", {}).get("observation", [])
            time_dim = next((d for d in dims_obs if d.get("id") == "TIME_PERIOD"), None)
            if not time_dim:
                return rows
            time_values = [v["id"] for v in time_dim.get("values", [])]

            dims_series = structure.get("dimensions", {}).get("series", [])
            loc_dim = next((d for d in dims_series if d.get("id") in ("LOCATION", "REF_AREA")), None)
            loc_values: list[str] = [v["id"] for v in loc_dim.get("values", [])] if loc_dim else []

            series_block = datasets[0].get("series", {})
            for series_key, series_data in series_block.items():
                # Estrai paese dall'indice
                country = "UNKNOWN"
                if loc_values and ":" in series_key:
                    parts = series_key.split(":")
                    if loc_dim:
                        loc_idx_pos = dims_series.index(loc_dim)
                        if loc_idx_pos < len(parts):
                            loc_idx = int(parts[loc_idx_pos])
                            if loc_idx < len(loc_values):
                                country = loc_values[loc_idx]

                obs = series_data.get("observations", {})
                for idx_str, obs_vals in obs.items():
                    idx = int(idx_str)
                    if idx >= len(time_values):
                        continue
                    period = time_values[idx]
                    val = obs_vals[0] if obs_vals else None
                    if val is None:
                        continue
                    try:
                        ts = self._parse_period(period)
                        rows.append({
                            "series_id": f"{series_prefix}_{country}",
                            "series_date": ts,
                            "value": float(val),
                            "country": country,
                            "source": "oecd",
                            "fetched_at": now,
                        })
                    except (ValueError, TypeError):
                        continue
        except Exception as exc:
            log.warning("oecd_fetcher.parse_error", error=str(exc)[:200])
        return rows

    def _parse_period(self, period: str) -> datetime:
        period = period.strip()
        if len(period) == 7:
            return datetime(int(period[:4]), int(period[5:7]), 1, tzinfo=UTC)
        if len(period) == 4:
            return datetime(int(period), 1, 1, tzinfo=UTC)
        return datetime(int(period[:4]), int(period[5:7]) if len(period) >= 7 else 1, 1, tzinfo=UTC)

    def _persist(self, df: pd.DataFrame) -> None:
        """Salva in macro_data (Regola 34)."""
        if df.empty:
            return
        try:
            for _, row in df.iterrows():
                self._client.execute(
                    """
                    INSERT INTO macro_data (series_id, series_date, value, source, unit, frequency, fetched_at)
                    VALUES (?, ?, ?, 'oecd', 'index', 'monthly', ?)
                    ON CONFLICT (series_id, series_date)
                    DO UPDATE SET value=excluded.value, fetched_at=excluded.fetched_at
                    """,
                    [row["series_id"], row["series_date"], row["value"], row["fetched_at"]],
                )
        except Exception as exc:
            log.warning("oecd_fetcher.persist_failed", error=str(exc)[:200])

    def __del__(self) -> None:
        try:
            self._http.close()
        except Exception:
            pass
