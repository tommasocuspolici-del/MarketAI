"""ECB Statistical Data Warehouse (SDW) Fetcher.

Sorgente: https://data.ecb.europa.eu/api/data/{dataset}/{series}
Gratuito, non richiede API key. Limite: ~30 req/min.
Regola 33: zero dati hardcoded.
Regola 34: cache-first (TTL: macro_ecb = 86400s).
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
__all__ = ["ECBFetcher"]

log = get_logger(__name__)

_BASE_URL = "https://data-api.ecb.europa.eu/service/data"
_TIMEOUT = 30.0
_DELAY_S = 2.0  # 30 req/min

# Serie ECB chiave per MarketAI
ECB_SERIES: dict[str, dict] = {
    # Tassi BCE
    "FM/B.U2.EUR.4F.KR.MRR_FR.LEV":   {"name": "ECB Main Refinancing Rate", "series_id": "ECB_MRR"},
    "FM/B.U2.EUR.4F.KR.MLFR.LEV":     {"name": "ECB Marginal Lending Facility", "series_id": "ECB_MLFR"},
    "FM/B.U2.EUR.4F.KR.DFR.LEV":      {"name": "ECB Deposit Facility Rate", "series_id": "ECB_DFR"},
    # Inflazione HICP
    "ICP/M.U2.N.000000.4.ANR":         {"name": "HICP YoY Euro Area", "series_id": "ECB_HICP_YOY"},
    # M3 Money Supply
    "BSI/M.U2.Y.V.M30.X.I.U2.2300.Z.A": {"name": "M3 Euro Area YoY", "series_id": "ECB_M3_YOY"},
    # EUR/USD
    "EXR/D.USD.EUR.SP00.A":            {"name": "EUR/USD Exchange Rate", "series_id": "ECB_EUR_USD"},
}


class ECBFetcher:
    """Fetcher per dati BCE (tassi, HICP, M3, cambi).

    Args:
        client: DuckDBClient per persistenza (Regola 34).

    Usage::

        fetcher = ECBFetcher(client=get_duckdb_client())
        df = fetcher.fetch_series("FM/B.U2.EUR.4F.KR.MRR_FR.LEV")
    """

    def __init__(self, client: DuckDBClient) -> None:
        self._client = client
        self._http = httpx.Client(
            timeout=_TIMEOUT,
            headers={"Accept": "application/json"},
        )

    def fetch_series(self, series_key: str, start_period: str = "2010-01") -> pd.DataFrame:
        """Scarica una singola serie ECB.

        Args:
            series_key:   Chiave ECB (es. 'FM/B.U2.EUR.4F.KR.MRR_FR.LEV').
            start_period: Periodo iniziale in formato YYYY-MM.

        Returns:
            DataFrame con colonne: series_id, series_date, value, source, fetched_at.
        """
        url = f"{_BASE_URL}/{series_key}"
        meta = ECB_SERIES.get(series_key, {"name": series_key, "series_id": f"ECB_{series_key.split('/')[-1][:20]}"})

        log.info("ecb_fetcher.fetch", series=series_key, name=meta["name"])
        try:
            time.sleep(_DELAY_S)
            resp = self._http.get(url, params={
                "startPeriod": start_period,
                "format": "jsondata",
            })
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise FetchError(source="ecb", detail=f"HTTP {exc.response.status_code}: {series_key}") from exc
        except Exception as exc:
            raise FetchError(source="ecb", detail=str(exc)) from exc

        rows = self._parse_json(data, meta["series_id"])
        if not rows:
            log.warning("ecb_fetcher.empty_response", series=series_key)
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        self._persist(df)
        log.info("ecb_fetcher.done", series=series_key, rows=len(df))
        return df

    def fetch_all(self) -> dict[str, pd.DataFrame]:
        """Scarica tutte le serie ECB configurate."""
        results: dict[str, pd.DataFrame] = {}
        for key, meta in ECB_SERIES.items():
            try:
                df = self.fetch_series(key)
                results[meta["series_id"]] = df
            except FetchError as exc:
                log.warning("ecb_fetcher.series_failed", series=key, error=str(exc))
        return results

    def _parse_json(self, data: dict, series_id: str) -> list[dict]:
        """Estrae osservazioni dal formato SDMX-JSON ECB."""
        rows = []
        now = datetime.now(UTC)
        try:
            ds = data.get("dataSets", [])
            if not ds:
                return rows
            series_block = ds[0].get("series", {})
            if not series_block:
                return rows
            obs = next(iter(series_block.values()), {}).get("observations", {})
            if not obs:
                return rows

            structure = data.get("structure", {})
            dims = structure.get("dimensions", {}).get("observation", [])
            time_dim = next((d for d in dims if d.get("id") == "TIME_PERIOD"), None)
            if time_dim is None:
                return rows
            time_values = [v["id"] for v in time_dim.get("values", [])]

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
                        "series_id": series_id,
                        "series_date": ts,
                        "value": float(val),
                        "source": "ecb",
                        "fetched_at": now,
                    })
                except (ValueError, TypeError):
                    continue
        except Exception as exc:
            log.warning("ecb_fetcher.parse_error", error=str(exc)[:200])
        return rows

    def _parse_period(self, period: str) -> datetime:
        """Converte YYYY-MM o YYYY-MM-DD in datetime UTC."""
        period = period.strip()
        if len(period) == 7:  # YYYY-MM
            return datetime(int(period[:4]), int(period[5:7]), 1, tzinfo=UTC)
        if len(period) == 10:  # YYYY-MM-DD
            return datetime(int(period[:4]), int(period[5:7]), int(period[8:10]), tzinfo=UTC)
        return datetime(int(period[:4]), 1, 1, tzinfo=UTC)

    def _persist(self, df: pd.DataFrame) -> None:
        """Salva in macro_data (Regola 34)."""
        if df.empty:
            return
        try:
            for _, row in df.iterrows():
                self._client.execute(
                    """
                    INSERT INTO macro_data (series_id, series_date, value, source, unit, frequency, fetched_at)
                    VALUES (?, ?, ?, 'ecb', 'percent', 'monthly', ?)
                    ON CONFLICT (series_id, series_date)
                    DO UPDATE SET value=excluded.value, fetched_at=excluded.fetched_at
                    """,
                    [row["series_id"], row["series_date"], row["value"], row["fetched_at"]],
                )
        except Exception as exc:
            log.warning("ecb_fetcher.persist_failed", error=str(exc)[:200])

    def __del__(self) -> None:
        try:
            self._http.close()
        except Exception:
            pass
