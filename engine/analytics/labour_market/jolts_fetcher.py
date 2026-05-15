"""JOLTS Fetcher — scarica dati mensili JOLTS da FRED e persiste in jolts_monthly.

Serie FRED target:
  JTSJOL  job_openings (migliaia, SA)
  JTSHIL  hires
  JTSQUL  quits
  JTSLAL  layoffs_discharges
  JTSQUR  quits_rate (%)
  JTSJOR  openings_rate (%)
  JTSHIR  hires_rate (%)
  UNRATE  unemployment_rate — per calcolo beveridge_gap

Regola 12: solo fetch→persist qui; nessuna analisi inline.
Regola 7: costanti con nome, zero magic numbers.
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

_TABLE = "jolts_monthly"

_FRED_SERIES: dict[str, str] = {
    "JTSJOL": "job_openings",
    "JTSHIL": "hires",
    "JTSQUL": "quits",
    "JTSLAL": "layoffs_discharges",
    "JTSQUR": "quits_rate",
    "JTSJOR": "openings_rate",
    "JTSHIR": "hires_rate",
}
_FRED_UNRATE = "UNRATE"

# JOLTS rilasciato con ritardo ~2 mesi
_MAX_OBSERVATIONS = 300  # ~25 anni mensili


class JOLTSFetcher:
    """Scarica e persiste dati JOLTS mensili da FRED.

    Args:
        client:      DuckDBClient per la persistenza.
        fred_client: FredSimpleClient per le chiamate API FRED.
    """

    def __init__(self, client: DuckDBClient, fred_client: FredSimpleClient) -> None:
        self._client = client
        self._fred = fred_client

    def fetch_and_persist(self, lookback_years: int = 20) -> int:
        """Scarica serie JOLTS da FRED e persiste in jolts_monthly.

        Args:
            lookback_years: Anni di storia da caricare (default 20).

        Returns:
            Numero di righe inserite/aggiornate.
        """
        start = date.today() - timedelta(days=lookback_years * 365)
        limit = lookback_years * 13  # margine per dati mensili

        raw: dict[str, pd.DataFrame] = {}
        for series_id, col in _FRED_SERIES.items():
            df = self._fetch_series(series_id, start, limit)
            if df is not None and not df.empty:
                raw[col] = df.rename(columns={"value": col})

        if not raw:
            log.warning("jolts_fetcher.no_data_available")
            return 0

        # Allinea su indice mensile comune
        base = self._align_monthly(raw)
        if base.empty:
            return 0

        # Aggiungi UNRATE per beveridge_gap
        unrate_df = self._fetch_series(_FRED_UNRATE, start, limit)
        if unrate_df is not None and not unrate_df.empty:
            unrate_m = (
                unrate_df.set_index("ts")["value"]
                .resample("MS").last()
                .rename("unrate")
            )
            base = base.join(unrate_m, how="left")
        else:
            base["unrate"] = None

        n = self._persist(base)
        log.info("jolts_fetcher.done rows=%d lookback_years=%d", n, lookback_years)
        return n

    def get_latest(self, lookback_months: int = 36) -> pd.DataFrame:
        """Legge gli ultimi N mesi da jolts_monthly.

        Returns:
            DataFrame con colonne della tabella jolts_monthly.
        """
        cutoff = date.today() - timedelta(days=lookback_months * 31)
        try:
            rows = self._client.query(
                f"SELECT series_date, job_openings, hires, quits, layoffs_discharges, "
                f"quits_rate, openings_rate, hires_rate, beveridge_gap, hires_quits_ratio "
                f"FROM {_TABLE} WHERE series_date >= ? ORDER BY series_date",
                [cutoff],
            )
            cols = ["series_date", "job_openings", "hires", "quits", "layoffs_discharges",
                    "quits_rate", "openings_rate", "hires_rate", "beveridge_gap",
                    "hires_quits_ratio"]
            return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)
        except Exception as exc:
            log.warning("jolts_fetcher.get_latest_failed: %s", str(exc)[:120])
            return pd.DataFrame()

    # ─── Internal helpers ─────────────────────────────────────────────────

    @apply_error_policy(level="RECOVER", fallback=None, context="JOLTSFetcher._fetch_series")
    def _fetch_series(self, series_id: str, start: date, limit: int) -> pd.DataFrame | None:
        df = self._fred.fetch_series(
            series_id, start=start, limit=limit, sort_order="asc"
        )
        # FredSimpleClient returns cols: ts, value
        df = df.dropna(subset=["value"])
        df = df[df["value"].astype(str) != "."]
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        return df.dropna(subset=["value"])

    @staticmethod
    def _align_monthly(raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Allinea tutte le serie su un indice mensile comune."""
        frames = {}
        for col, df in raw.items():
            s = df.set_index("ts")[col].resample("MS").last()
            frames[col] = s
        if not frames:
            return pd.DataFrame()
        base = pd.DataFrame(frames)
        base.index.name = "series_date"
        return base.reset_index()

    def _persist(self, df: pd.DataFrame) -> int:
        n = 0
        for _, row in df.iterrows():
            series_date = row["series_date"]
            if pd.isna(series_date):
                continue
            if isinstance(series_date, pd.Timestamp):
                series_date = series_date.date()

            job_openings = _f(row, "job_openings")
            hires        = _f(row, "hires")
            quits        = _f(row, "quits")
            layoffs      = _f(row, "layoffs_discharges")
            quits_rate   = _f(row, "quits_rate")
            openings_rate= _f(row, "openings_rate")
            hires_rate   = _f(row, "hires_rate")
            unrate        = _f(row, "unrate")

            beveridge_gap = (
                round(openings_rate - unrate, 4)
                if openings_rate is not None and unrate is not None
                else None
            )
            hires_quits_ratio = (
                round(hires / quits, 4)
                if hires is not None and quits and quits > 0
                else None
            )

            try:
                self._client.execute(
                    f"""
                    INSERT INTO {_TABLE}
                        (series_date, job_openings, hires, quits, layoffs_discharges,
                         quits_rate, openings_rate, hires_rate, beveridge_gap, hires_quits_ratio)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT (series_date) DO UPDATE SET
                        job_openings=excluded.job_openings,
                        hires=excluded.hires,
                        quits=excluded.quits,
                        layoffs_discharges=excluded.layoffs_discharges,
                        quits_rate=excluded.quits_rate,
                        openings_rate=excluded.openings_rate,
                        hires_rate=excluded.hires_rate,
                        beveridge_gap=excluded.beveridge_gap,
                        hires_quits_ratio=excluded.hires_quits_ratio,
                        fetched_at=NOW()
                    """,
                    [series_date, job_openings, hires, quits, layoffs,
                     quits_rate, openings_rate, hires_rate, beveridge_gap,
                     hires_quits_ratio],
                )
                n += 1
            except Exception as exc:
                log.debug("jolts_fetcher.persist_row_failed: %s", str(exc)[:80])
        return n


def _f(row: pd.Series, col: str) -> float | None:
    """Legge un valore float da una riga, None se assente o NaN."""
    val = row.get(col)
    if val is None or (hasattr(val, "__float__") and pd.isna(val)):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
