"""Fetch e persist della serie storica CAPE Shiller (1881–oggi).

Fonti (in ordine di priorità):
  1. Dataset pubblico Shiller Yale (XLS) — dati dal 1881
  2. FRED series (SP500EPS, SP500, CPIAUCSL, DGS10) — proxy CAPE

Pipeline: fetch → compute CAPE → persist in shiller_cape_historical.

Regola 12: nessun fetch inline; usare sempre questo modulo.
Regola 27: persist via DuckDB client.
"""
from __future__ import annotations

from shared.logger import get_logger
import io
import re
from datetime import date, timedelta
from typing import TYPE_CHECKING

import httpx
import numpy as np
import pandas as pd

from shared.resilience.error_policy import apply_error_policy, error_policy, ErrorLevel

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.1.0"
log = get_logger(__name__)

# Source URLs in ordine di preferenza:
#   1. Homepage shillerdata.com (scrape link aggiornato, file ospitato su wsimg.com)
#   2. URL diretto wsimg.com noto (fallback con token che potrebbe ruotare)
#   3. Vecchio URL Yale (stale al 2023-09 ma sempre raggiungibile)
_SHILLER_HOMEPAGE = "https://shillerdata.com/"
_SHILLER_URL_FALLBACK_WSIMG = (
    "https://img1.wsimg.com/blobby/go/e5e77e0b-59d1-44d9-ab25-4763ac982e53/"
    "downloads/441f0d2c-37e4-4803-b4e2-8fe10407fbf6/ie_data.xls"
)
_SHILLER_URL_YALE_LEGACY = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"
_HTTP_TIMEOUT_S = 30.0
_USER_AGENT = "MarketAI/12.1.0 (+research)"

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
        fred_client: object = None,
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
        log.info("shiller_cape_fetcher.done rows=%d lookback_years=%d", n, lookback_years)
        return n

    @staticmethod
    def _resolve_shiller_url(http: httpx.Client) -> str | None:
        """Scrape shillerdata.com per il link corrente del file ``ie_data.xls``.

        Il file e' ospitato su ``img1.wsimg.com`` con un token nel path che la
        homepage di Shiller aggiorna ad ogni rilascio. Scraping HTML e' la
        strada ufficiale documentata sulla homepage.
        """
        try:
            r = http.get(_SHILLER_HOMEPAGE)
            r.raise_for_status()
            # I link sono protocol-relative: '//img1.wsimg.com/...'
            matches = re.findall(
                r'href="(//img1\.wsimg\.com/[^"]*ie_data\.xls[^"]*)"',
                r.text, re.IGNORECASE,
            )
            if matches:
                return "https:" + matches[0]
        except Exception as exc:
            log.warning("shiller_cape_fetcher.scrape_homepage_failed",
                        error=str(exc)[:100])
        return None

    @apply_error_policy(level="RECOVER", fallback=None, context="ShillerCAPEFetcher._fetch_shiller_xls")
    def _fetch_shiller_xls(self) -> pd.DataFrame | None:
        """Download e parsing XLS Shiller.

        Tenta in sequenza: scrape shillerdata.com -> URL wsimg conosciuto
        -> URL Yale legacy (stale a 2023-09 ma sempre disponibile).
        """
        http = httpx.Client(timeout=_HTTP_TIMEOUT_S, follow_redirects=True,
                            headers={"User-Agent": _USER_AGENT})
        try:
            scraped = self._resolve_shiller_url(http)
            urls_to_try: list[str] = [
                u for u in (scraped, _SHILLER_URL_FALLBACK_WSIMG, _SHILLER_URL_YALE_LEGACY)
                if u is not None
            ]
            content: bytes | None = None
            chosen_url: str | None = None
            for url in urls_to_try:
                try:
                    log.info("shiller_cape_fetcher.downloading_xls", url=url[:80])
                    resp = http.get(url)
                    if resp.status_code == 200 and len(resp.content) > 100_000:
                        content = resp.content
                        chosen_url = url
                        break
                    log.warning("shiller_cape_fetcher.url_rejected",
                                url=url[:80], status=resp.status_code,
                                size=len(resp.content))
                except Exception as exc:
                    log.warning("shiller_cape_fetcher.url_failed",
                                url=url[:80], error=str(exc)[:100])
        finally:
            http.close()

        if content is None:
            log.error("shiller_cape_fetcher.all_sources_failed")
            return None
        log.info("shiller_cape_fetcher.xls_downloaded",
                 bytes=len(content), source=chosen_url[:80] if chosen_url else "?")

        xls = pd.ExcelFile(io.BytesIO(content), engine="xlrd")
        # Foglio "Data" con skiprows per header multi-riga Shiller
        df_raw = pd.read_excel(xls, sheet_name="Data", skiprows=7, header=0)

        # Shiller XLS "Data" sheet layout (2024+ version, 22 columns):
        #   [0] Date(YYYY.MM)  [1] P  [2] D  [3] E  [4] CPI  [5] Fraction
        #   [6] Rate GS10      [7] Price(real) [8] Dividend(real)
        #   [9] Price.1        [10] Earnings(real) [11] Earnings.1
        #   [12] CAPE          [13] Unnamed  [14] TR CAPE  …
        df_raw.columns = [str(c).strip() for c in df_raw.columns]

        # Locate CAPE column by name first, then fall back to known index 12
        col_names_lower = [c.lower() for c in df_raw.columns]
        if "cape" in col_names_lower:
            cape_idx = col_names_lower.index("cape")
        else:
            cape_idx = 12

        # 'Rate GS10' is the 10Y bond yield (percentage, e.g. 4.57 = 4.57%)
        if "rate gs10" in col_names_lower:
            yield_idx: int | None = col_names_lower.index("rate gs10")
        else:
            yield_idx = 6 if df_raw.shape[1] > 6 else None

        # Parse Date (format: 1881.01 = January 1881)
        date_col  = df_raw.iloc[:, 0]
        prices    = pd.to_numeric(df_raw.iloc[:, 1], errors="coerce")
        earnings  = pd.to_numeric(df_raw.iloc[:, 3], errors="coerce")
        cpi       = pd.to_numeric(df_raw.iloc[:, 4], errors="coerce")
        cape_col  = pd.to_numeric(df_raw.iloc[:, cape_idx] if df_raw.shape[1] > cape_idx else pd.Series([np.nan] * len(df_raw)), errors="coerce")
        yield_col = pd.to_numeric(df_raw.iloc[:, yield_idx] if yield_idx is not None else pd.Series([np.nan] * len(df_raw)), errors="coerce")

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

            price  = float(prices.iloc[i])   if pd.notna(prices.iloc[i])   else None
            eps    = float(earnings.iloc[i])  if pd.notna(earnings.iloc[i]) else None  # noqa: F841
            cape   = float(cape_col.iloc[i])  if pd.notna(cape_col.iloc[i]) else None
            cpi_v  = float(cpi.iloc[i])       if pd.notna(cpi.iloc[i])      else None
            gs10   = float(yield_col.iloc[i]) if pd.notna(yield_col.iloc[i]) else None

            ey = (1.0 / cape) if (cape and cape > 0) else None
            ry = gs10 / 100.0 if gs10 is not None else None
            erp = (ey - ry) if (ey is not None and ry is not None) else None

            records.append({
                "data_date":        data_date,
                "sp500_price":      price,
                "eps_10y_real_avg": price / cape if (cape and cape > 0 and price) else None,
                "cape_ratio":       cape,
                "bond_yield":       gs10,   # stored as %, e.g. 4.57
                "erp_implied":      erp,
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
        fred: FredSimpleClient = self._fred  # type: ignore[assignment]

        from datetime import date, timedelta
        start = date.today() - timedelta(days=(lookback_years + 10) * 365)
        eps_df   = fred.fetch_series("SP500EPS",  start=start, limit=(lookback_years + 10) * 13, sort_order="asc")
        cpi_df   = fred.fetch_series("CPIAUCSL",  start=start, limit=(lookback_years + 10) * 13, sort_order="asc")
        dgs10_df = fred.fetch_series("DGS10",     start=date.today() - timedelta(days=lookback_years * 365), limit=lookback_years * 13, sort_order="asc")
        sp500_df = fred.fetch_series("SP500",     start=date.today() - timedelta(days=lookback_years * 365), limit=lookback_years * 13, sort_order="asc")

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
                log.debug("shiller_cape_fetcher.persist_row_failed: %s", str(exc)[:80])
        return n

    def get_latest_cape(self) -> float | None:
        """Legge il CAPE più recente da DuckDB."""
        try:
            rows = self._client.query(
                f"SELECT cape_ratio FROM {_TABLE} "
                f"WHERE cape_ratio IS NOT NULL ORDER BY data_date DESC LIMIT 1"
            )
            return float(rows[0][0]) if rows and rows[0][0] is not None else None
        except Exception as exc:
            return error_policy.handle(exc, level=ErrorLevel.RECOVER, context="shiller_cape_fetcher", fallback=None)

    def get_history(self, years: int = 20) -> list[object]:
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
