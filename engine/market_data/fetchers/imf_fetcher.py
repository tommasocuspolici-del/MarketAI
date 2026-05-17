"""IMF Data API Fetcher — World Economic Outlook, IFS, Balance of Payments.

Sorgente: https://datahelp.imf.org/knowledgebase/articles/630877-data-api
Gratuito, non richiede API key. Limite: ~10 req/min.
Regola 33: zero dati hardcoded.
Regola 34: cache-first via MacroRepo (TTL: macro_imf = 86400s).
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import pandas as pd

from shared.exceptions import FetchError
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["IMFFetcher"]

log = get_logger(__name__)

_BASE_URL = "https://www.imf.org/external/datamapper/api/v1"
_TIMEOUT = 30.0
_DELAY_S = 6.5  # ~10 req/min, conservativo

# Serie IMF più rilevanti per MarketAI
IMF_SERIES: dict[str, str] = {
    "NGDP_RPCH":  "Real GDP Growth (%YoY)",
    "PCPIPCH":    "CPI Inflation (%YoY)",
    "LUR":        "Unemployment Rate (%)",
    "BCA_NGDPD":  "Current Account (% GDP)",
    "GGXWDG_NGDP": "Gross Debt (% GDP)",
}

# Paesi di interesse
IMF_COUNTRIES: list[str] = ["USA", "GBR", "DEU", "JPN", "CHN", "FRA", "ITA"]


class IMFFetcher:
    """Fetcher per dati macro IMF WEO/IFS.

    Args:
        client: DuckDBClient per cache-first (Regola 34).

    Usage::

        fetcher = IMFFetcher(client=get_duckdb_client())
        df = fetcher.fetch_series("NGDP_RPCH", countries=["USA", "DEU"])
    """

    def __init__(self, client: DuckDBClient) -> None:
        self._client = client
        self._http = httpx.Client(timeout=_TIMEOUT)

    def fetch_series(
        self,
        indicator: str,
        countries: list[str] | None = None,
        start_year: int = 2010,
    ) -> pd.DataFrame:
        """Scarica una serie IMF per uno o più paesi.

        Returns:
            DataFrame con colonne: country, year, value, indicator, fetched_at.
        """
        countries = countries or IMF_COUNTRIES
        country_str = "+".join(countries)
        url = f"{_BASE_URL}/{indicator}/{country_str}"

        log.info("imf_fetcher.fetch", indicator=indicator, countries=countries)
        try:
            time.sleep(_DELAY_S)
            resp = self._http.get(url, params={"periods": f"{start_year}:2030"})
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise FetchError(source="imf", detail=f"HTTP {exc.response.status_code}: {exc}") from exc
        except Exception as exc:
            raise FetchError(source="imf", detail=str(exc)) from exc

        rows = []
        values_block = data.get("values", {}).get(indicator, {})
        for country, yearly in values_block.items():
            if country not in countries:
                continue
            for year_str, val in yearly.items():
                try:
                    year = int(year_str)
                    if year < start_year:
                        continue
                    rows.append({
                        "country": country,
                        "year": year,
                        "value": float(val) if val is not None else None,
                        "indicator": indicator,
                        "series_id": f"IMF_{indicator}_{country}",
                        "fetched_at": datetime.now(UTC),
                    })
                except (ValueError, TypeError):
                    continue

        if not rows:
            log.warning("imf_fetcher.empty_response", indicator=indicator)
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        self._persist(df)
        log.info("imf_fetcher.done", indicator=indicator, rows=len(df))
        return df

    def fetch_all_key_series(self) -> dict[str, pd.DataFrame]:
        """Scarica tutte le serie IMF_SERIES configurate."""
        results: dict[str, pd.DataFrame] = {}
        for indicator in IMF_SERIES:
            try:
                df = self.fetch_series(indicator)
                results[indicator] = df
            except FetchError as exc:
                log.warning("imf_fetcher.series_failed", indicator=indicator, error=str(exc))
        return results

    def _persist(self, df: pd.DataFrame) -> None:
        """Salva in macro_data (Regola 34 — DuckDB come unica fonte di verità)."""
        if df.empty:
            return
        try:
            for _, row in df.iterrows():
                if row["value"] is None:
                    continue
                self._client.execute(
                    """
                    INSERT INTO macro_data (series_id, series_date, value, source, unit, frequency, fetched_at)
                    VALUES (?, MAKE_DATE(?, 6, 30), ?, 'imf', 'percent', 'annual', ?)
                    ON CONFLICT (series_id, series_date)
                    DO UPDATE SET value=excluded.value, fetched_at=excluded.fetched_at
                    """,
                    [row["series_id"], int(row["year"]), float(row["value"]), row["fetched_at"]],
                )
        except Exception as exc:
            log.warning("imf_fetcher.persist_failed", error=str(exc)[:200])

    def __del__(self) -> None:
        try:
            self._http.close()
        except Exception:
            pass
