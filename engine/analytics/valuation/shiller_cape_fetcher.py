"""Fetch e persist della serie storica CAPE Shiller (1881–oggi).

Fonti (in ordine di priorità):
  1. Dataset pubblico Shiller Yale (XLS) — dati dal 1881
  2. FRED series (SP500EPS, SP500, CPIAUCSL, DGS10) — proxy CAPE

Pipeline: fetch → compute CAPE → persist in shiller_cape_historical.

Regola 12: nessun fetch inline; usare sempre questo modulo.
Regola 27: persist via DuckDB client.
"""
from __future__ import annotations

import io
import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from shared.resilience.error_policy import apply_error_policy

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
log = logging.getLogger(__name__)

# Yale URL dataset Shiller (aggiornamento mensile)
_SHILLER_URL = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"

# FRED series per proxy CAPE quando Shiller non disponibile
_FRED_SERIES = {
    "SP500EPS": "sp500_eps",       # S&P 500 Earnings Per Share
    "CPIAUCSL": "cpi",             # CPI All Urban (per aggiustamento reale)
    "DGS10":    "bond_yield",      # US 10Y Treasury
}

_TABLE = "shiller_cape_historical"


class ShillerCAPEFetcher:
    """Scarica e persiste la serie storica CAPE Shiller.

    Args:
        client: DuckDBClient per la persistenza.
        fred_client: FredSimpleClient per il fallback FRED.
    """

    def __init__(
        self,
        client: DuckDBClient,
        fred_client=None,
    ) -> None:
        self._client = client
        self._fred = fred_client

    def fetch_and_persist(self, lookback_years: int = 30) -> int:
        """Scarica dati Shiller e persiste in DuckDB.

        Args:
            lookback_years: Anni di storia da caricare (default 30).

        Returns:
            Numero di righe inserite/aggiornate.
        """
        df = self._fetch_shiller_xls()
        if df is None or df.empty:
            df = self._fetch_from_fred(lookback_years)
        if df is None or df.empty:
            log.warning("shiller_cape_fetcher: nessuna fonte disponibile")
            return 0

        # Filtra per lookback
        cutoff = date.today() - timedelta(days=lookback_years * 365)
        df = df[df["data_date"] >= cutoff].copy()

        n = self._persist(df)
        log.info("shiller_cape_fetcher.done", rows=n, lookback_years=lookback_years)
        return n

    @apply_error_policy(level="RECOVER", fallback=None, context="ShillerCAPEFetcher._fetch_shiller_xls")
    def _fetch_shiller_xls(self) -> pd.DataFrame | None:
        """Download e parsing XLS da Shiller Yale."""
        import urllib.request
        log.info("shiller_cape_fetcher.downloading_xls", url=_SHILLER_URL)
        with urllib.request.urlopen(_SHILLER_URL, timeout=30) as resp:
            content = resp.read()

        xls = pd.ExcelFile(io.BytesIO(content), engine="xlrd")
        # Foglio "Data" con skiprows per header multi-riga Shiller
        df_raw = pd.read_excel(xls, sheet_name="Data", skiprows=7, header=0)

        # Colonne Shiller: A=Date(YYYY.MM), B=P, C=D, D=E, E=CPI, F=Fraction
        # G=Real Price, H=Real Dividend, I=Real Earnings, J=CAPE
        df_raw.columns = [str(c).strip() for c in df_raw.columns]

        # Parse Date (format: 1881.01 = January 1881)
        date_col = df_raw.iloc[:, 0]
        prices   = pd.to_numeric(df_raw.iloc[:, 1], errors="coerce")
        earnings = pd.to_numeric(df_raw.iloc[:, 3], errors="coerce")
        cpi      = pd.to_numeric(df_raw.iloc[:, 4], errors="coerce")
        # CAPE in colonna J (index 9)
        cape_col = pd.to_numeric(df_raw.iloc[:, 9] if df_raw.shape[1] > 9 else pd.Series([np.nan]*len(df_raw)), errors="coerce")

        records = []
        for i, raw_date in enumerate(date_col):
            try:
                d_float = float(raw_date)
                year  = int(d_float)
                month = round((d_float - year) * 100)
                if month == 0:
                    month = 1
                data_date = date(year, month, 1)
            except (TypeError, ValueError):
                continue

            price = float(prices.iloc[i]) if pd.notna(prices.iloc[i]) else None
            eps   = float(earnings.iloc[i]) if pd.notna(earnings.iloc[i]) else None
            cape  = float(cape_col.iloc[i]) if pd.notna(cape_col.iloc[i]) else None
            cpi_v = float(cpi.iloc[i]) if pd.notna(cpi.iloc[i]) else None

            records.append({
                "data_date":        data_date,
                "sp500_price":      price,
                "eps_10y_real_avg": price / cape if (cape and cape > 0 and price) else None,
                "cape_ratio":       cape,
                "bond_yield":       None,
                "erp_implied":      None,
                "cpi_level":        cpi_v,
                "source":           "shiller_yale",
            })

        return pd.DataFrame(records)

    @apply_error_policy(level="RECOVER", fallback=None, context="ShillerCAPEFetcher._fetch_from_fred")
    def _fetch_from_fred(self, lookback_years: int = 30) -> pd.DataFrame | None:
        """Fallback: costruisce serie CAPE approssimata da dati FRED.

        Usa SP500EPS (trimestrale) e CPIAUCSL per rolling 10Y real EPS.
        """
        if self._fred is None:
            log.warning("shiller_cape_fetcher.fred_not_available")
            return None

        from engine.market_data.fred_simple_client import FredSimpleClient
        fred: FredSimpleClient = self._fred

        eps_df   = fred.fetch("SP500EPS",  lookback_years=lookback_years + 10)
        cpi_df   = fred.fetch("CPIAUCSL",  lookback_years=lookback_years + 10)
        dgs10_df = fred.fetch("DGS10",     lookback_years=lookback_years)
        sp500_df = fred.fetch("SP500",     lookback_years=lookback_years)

        if eps_df is None or eps_df.empty or sp500_df is None or sp500_df.empty:
            return None

        # Resample mensile
        eps_m = eps_df.resample("ME")["value"].last().dropna()
        cpi_m = cpi_df.resample("ME")["value"].last().dropna() if cpi_df is not None else None
        sp_m  = sp500_df.resample("ME")["value"].last().dropna()

        # Real EPS (CPI adjusted)
        if cpi_m is not None and not cpi_m.empty:
            cpi_latest = float(cpi_m.iloc[-1])
            real_eps = eps_m * (cpi_latest / cpi_m.reindex(eps_m.index, method="ffill"))
        else:
            real_eps = eps_m

        # Rolling 10Y real EPS mean
        real_eps_10y = real_eps.rolling(120, min_periods=60).mean()

        # CAPE = Price / real_eps_10y
        cape = sp_m / real_eps_10y.reindex(sp_m.index, method="ffill")

        dgs10_r = None
        if dgs10_df is not None and not dgs10_df.empty:
            dgs10_r = dgs10_df.resample("ME")["value"].last()

        records = []
        for idx in sp_m.index:
            dt = idx.date() if hasattr(idx, "date") else idx
            p  = float(sp_m[idx]) if idx in sp_m.index else None
            c  = float(cape[idx]) if idx in cape.index and pd.notna(cape[idx]) else None
            ey = 1.0 / c if c and c > 0 else None
            ry = float(dgs10_r[idx]) / 100.0 if (dgs10_r is not None and idx in dgs10_r.index and pd.notna(dgs10_r[idx])) else None
            records.append({
                "data_date":        dt,
                "sp500_price":      p,
                "eps_10y_real_avg": float(real_eps_10y[idx]) if idx in real_eps_10y.index and pd.notna(real_eps_10y[idx]) else None,
                "cape_ratio":       c,
                "bond_yield":       ry * 100 if ry is not None else None,
                "erp_implied":      (ey - ry) if (ey and ry) else None,
                "cpi_level":        None,
                "source":           "fred_computed",
            })

        return pd.DataFrame(records)

    def _persist(self, df: pd.DataFrame) -> int:
        """Upsert in shiller_cape_historical."""
        if df.empty:
            return 0
        n = 0
        for _, row in df.iterrows():
            if row.get("data_date") is None:
                continue
            try:
                self._client.execute(
                    f"""
                    INSERT INTO {_TABLE}
                        (data_date, sp500_price, eps_10y_real_avg, cape_ratio,
                         bond_yield, erp_implied, cpi_level, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (data_date) DO UPDATE SET
                        cape_ratio       = excluded.cape_ratio,
                        sp500_price      = excluded.sp500_price,
                        eps_10y_real_avg = excluded.eps_10y_real_avg,
                        bond_yield       = COALESCE(excluded.bond_yield, {_TABLE}.bond_yield),
                        erp_implied      = excluded.erp_implied,
                        fetched_at       = NOW()
                    """,
                    [
                        row["data_date"], row.get("sp500_price"),
                        row.get("eps_10y_real_avg"), row.get("cape_ratio"),
                        row.get("bond_yield"), row.get("erp_implied"),
                        row.get("cpi_level"), row.get("source", "unknown"),
                    ],
                )
                n += 1
            except Exception as exc:
                log.debug("shiller_cape_fetcher.persist_row_failed", error=str(exc)[:80])
        return n

    def get_latest_cape(self) -> float | None:
        """Legge il CAPE più recente da DuckDB."""
        try:
            rows = self._client.query(
                f"SELECT cape_ratio FROM {_TABLE} "
                f"WHERE cape_ratio IS NOT NULL ORDER BY data_date DESC LIMIT 1"
            )
            return float(rows[0][0]) if rows and rows[0][0] is not None else None
        except Exception:
            return None

    def get_history(self, years: int = 20) -> list:
        """Legge la serie storica CAPE come lista di ShillerCAPEPoint."""
        from engine.analytics.valuation.schemas import ShillerCAPEPoint
        df = self.get_historical(lookback_years=years)
        if df.empty:
            return []
        return [
            ShillerCAPEPoint(
                data_date=row["data_date"],
                sp500_price=row.get("sp500_price"),
                eps_10y_real_avg=row.get("eps_10y_real_avg"),
                cape_ratio=row.get("cape_ratio"),
                bond_yield=row.get("bond_yield"),
                erp_implied=row.get("erp_implied"),
            )
            for _, row in df.iterrows()
        ]

    # Alias for patching in tests
    _fetch_from_web = _fetch_shiller_xls

    def get_historical(self, lookback_years: int = 20) -> pd.DataFrame:
        """Legge la serie storica CAPE da DuckDB.

        Returns:
            DataFrame con colonne: data_date, cape_ratio, erp_implied, sp500_price.
        """
        cutoff = date.today() - timedelta(days=lookback_years * 365)
        rows = self._client.query(
            f"SELECT data_date, sp500_price, eps_10y_real_avg, cape_ratio, "
            f"bond_yield, erp_implied FROM {_TABLE} "
            f"WHERE data_date >= ? ORDER BY data_date",
            [cutoff],
        )
        if not rows:
            return pd.DataFrame(columns=["data_date", "sp500_price", "eps_10y_real_avg",
                                         "cape_ratio", "bond_yield", "erp_implied"])
        return pd.DataFrame(rows, columns=["data_date", "sp500_price", "eps_10y_real_avg",
                                           "cape_ratio", "bond_yield", "erp_implied"])
