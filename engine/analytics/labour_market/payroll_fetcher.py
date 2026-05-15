"""Payroll Fetcher — scarica dati NFP per settore da FRED e persiste in payroll_sector.

Serie FRED target:
  PAYEMS   total_nonfarm (riferimento, migliaia)
  MANEMP   manufacturing
  USCONS   construction
  USMINE   mining_logging
  USTPU    trade_transport_utilities
  USINFO   information
  USFIRE   financial
  USPBS    professional_business
  USEHS    education_health
  USLAH    leisure_hospitality
  USGOVT   government

Calcoli derivati:
  jobs_added_k       = variazione MoM (diff primo ordine)
  prev_month_revised = differenza tra release corrente e precedente per lo stesso mese
  yoy_pct            = (livello / livello_52w_ago - 1) * 100
  share_of_total     = settore / total_nonfarm * 100

Regola 12: solo fetch→persist; nessuna analisi inline.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING

import pandas as pd

from shared.resilience.error_policy import apply_error_policy

if TYPE_CHECKING:
    from engine.market_data.fred_simple_client import FredSimpleClient
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
log = logging.getLogger(__name__)

_TABLE = "payroll_sector"

_FRED_SECTORS: dict[str, tuple[str, bool]] = {
    # serie_id → (nome_settore, is_cyclical)
    "PAYEMS": ("total_nonfarm",          False),
    "MANEMP": ("manufacturing",          True),
    "USCONS": ("construction",           True),
    "USMINE": ("mining_logging",         True),
    "USTPU":  ("trade_transport_util",   False),
    "USINFO": ("information",            True),
    "USFIRE": ("financial",              False),
    "USPBS":  ("professional_business",  True),
    "USEHS":  ("education_health",       False),
    "USLAH":  ("leisure_hospitality",    True),
    "USGOVT": ("government",             False),
}

_YOY_LAG = 12  # mesi


class PayrollFetcher:
    """Scarica e persiste dati NFP per settore da FRED.

    Args:
        client:      DuckDBClient per la persistenza.
        fred_client: FredSimpleClient per le chiamate API FRED.
    """

    def __init__(self, client: DuckDBClient, fred_client: FredSimpleClient) -> None:
        self._client = client
        self._fred = fred_client

    def fetch_and_persist(self, lookback_years: int = 20) -> int:
        """Scarica NFP per settore da FRED e persiste in payroll_sector.

        Args:
            lookback_years: Anni di storia da caricare.

        Returns:
            Numero di righe inserite/aggiornate totali.
        """
        start = date.today() - timedelta(days=lookback_years * 365)
        limit = lookback_years * 13

        series_data: dict[str, pd.Series] = {}
        for series_id, (sector_name, _) in _FRED_SECTORS.items():
            df = self._fetch_series(series_id, start, limit)
            if df is not None and not df.empty:
                s = df.set_index("ts")["value"].sort_index()
                s.index = s.index.to_period("M").to_timestamp()
                series_data[sector_name] = s

        if "total_nonfarm" not in series_data:
            log.warning("payroll_fetcher.total_nonfarm_unavailable")
            return 0

        total = series_data["total_nonfarm"]
        n_total = 0
        for series_id, (sector_name, is_cyclical) in _FRED_SECTORS.items():
            if sector_name not in series_data:
                continue
            level = series_data[sector_name]
            n_total += self._persist_sector(
                level, sector_name, is_cyclical, total
            )

        log.info("payroll_fetcher.done rows=%d lookback_years=%d", n_total, lookback_years)
        return n_total

    def get_latest(self, lookback_months: int = 36) -> pd.DataFrame:
        """Legge gli ultimi N mesi da payroll_sector."""
        cutoff = date.today() - timedelta(days=lookback_months * 31)
        try:
            rows = self._client.query(
                f"SELECT release_date, sector, jobs_added_k, prev_month_revised, "
                f"yoy_pct, share_of_total, is_cyclical "
                f"FROM {_TABLE} WHERE release_date >= ? ORDER BY release_date, sector",
                [cutoff],
            )
            cols = ["release_date", "sector", "jobs_added_k", "prev_month_revised",
                    "yoy_pct", "share_of_total", "is_cyclical"]
            return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)
        except Exception as exc:
            log.warning("payroll_fetcher.get_latest_failed: %s", str(exc)[:120])
            return pd.DataFrame()

    # ─── Internal helpers ─────────────────────────────────────────────────

    @apply_error_policy(level="RECOVER", fallback=None, context="PayrollFetcher._fetch_series")
    def _fetch_series(self, series_id: str, start: date, limit: int) -> pd.DataFrame | None:
        df = self._fred.fetch_series(
            series_id, start=start, limit=limit, sort_order="asc"
        )
        df = df.dropna(subset=["value"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        return df.dropna(subset=["value"])

    def _persist_sector(
        self,
        level: pd.Series,
        sector_name: str,
        is_cyclical: bool,
        total: pd.Series,
    ) -> int:
        jobs_added    = level.diff(1)
        prev_revised  = level.diff(1) - level.shift(1).diff(1)
        yoy           = (level / level.shift(_YOY_LAG) - 1.0) * 100.0
        total_aligned = total.reindex(level.index)
        share         = (level / total_aligned * 100.0).where(total_aligned > 0)

        n = 0
        for idx in level.index:
            release_date = idx.date() if hasattr(idx, "date") else idx
            try:
                self._client.execute(
                    f"""
                    INSERT INTO {_TABLE}
                        (release_date, sector, jobs_added_k, prev_month_revised,
                         yoy_pct, share_of_total, is_cyclical)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT (release_date, sector) DO UPDATE SET
                        jobs_added_k=excluded.jobs_added_k,
                        prev_month_revised=excluded.prev_month_revised,
                        yoy_pct=excluded.yoy_pct,
                        share_of_total=excluded.share_of_total,
                        is_cyclical=excluded.is_cyclical
                    """,
                    [
                        release_date,
                        sector_name,
                        _fv(jobs_added, idx),
                        _fv(prev_revised, idx),
                        _fv(yoy, idx),
                        _fv(share, idx),
                        is_cyclical,
                    ],
                )
                n += 1
            except Exception as exc:
                log.debug("payroll_fetcher.persist_row_failed: %s", str(exc)[:80])
        return n


def _fv(series: pd.Series, idx: object) -> float | None:
    """Legge un valore float da una Series, None se NaN o assente."""
    if idx not in series.index:
        return None
    val = series[idx]
    if pd.isna(val):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
