"""FRED (Federal Reserve Economic Data) macro fetcher.

Uses ``pandas-datareader`` (sync) wrapped in asyncio.to_thread to honor
Rule 11. FRED is the most stable free macro source — no API key strictly
required, but providing one increases the soft rate limit. Read from
``FRED_API_KEY`` env (Rule 15).

Rate limit configured under ``fred`` in ``config/rate_limits.yaml``.
"""
from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

import pandas as pd

from engine.market_data.fetchers.base_fetcher import BaseMacroFetcher
from shared.exceptions import FetchError
from shared.logger import get_logger
from shared.types import DataSource, ensure_utc

if TYPE_CHECKING:
    from datetime import datetime

    from engine.market_data.cleaning import DataCleaner
    from shared.db.dual_writer import DualWriter
    from shared.db.quality import QualityReportRepository
    from shared.rate_limit_manager import RateLimitManager

__version__ = "6.0.0"

__all__ = ["FRED_KEY_SERIES", "FREDFetcher"]

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Curated catalog: ~50 KEY FRED series — used by scripts/bulk_fred_download.py
# ═══════════════════════════════════════════════════════════════════════════
# Lista non esaustiva: la roadmap menziona "600 serie", che è il superset
# globale FRED rilevante. Qui includiamo le ~50 essenziali per dashboard
# Macro (E6) — ulteriori serie possono essere aggiunte tramite YAML.
FRED_KEY_SERIES: tuple[str, ...] = (
    # ─── Output / GDP ───────────────────────────────────────────────────
    "GDP", "GDPC1", "GDPPOT", "PAYEMS", "INDPRO", "IPMAN",
    # ─── Inflation ──────────────────────────────────────────────────────
    "CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE", "T5YIE", "T10YIE",
    # ─── Labor market ──────────────────────────────────────────────────
    "UNRATE", "U6RATE", "CIVPART", "ICSA", "JTSJOL", "AHETPI",
    # ─── Interest rates / yield curve ──────────────────────────────────
    "FEDFUNDS", "DFF", "DGS2", "DGS5", "DGS10", "DGS30", "T10Y2Y", "T10Y3M",
    # ─── Money supply / credit ─────────────────────────────────────────
    "M2SL", "BOGMBASE", "TOTRESNS", "WALCL",
    # ─── Housing ───────────────────────────────────────────────────────
    "HOUST", "PERMIT", "CSUSHPISA", "MORTGAGE30US",
    # ─── Consumer ──────────────────────────────────────────────────────
    "UMCSENT", "RSAFS", "PCE",
    # ─── International ─────────────────────────────────────────────────
    "DEXUSEU", "DEXJPUS", "DEXCHUS", "DEXUSUK",
    # ─── Risk indicators ────────────────────────────────────────────────
    "VIXCLS", "BAMLH0A0HYM2", "BAMLC0A0CM", "TEDRATE",
    # ─── Energy / commodities ──────────────────────────────────────────
    "DCOILWTICO", "DCOILBRENTEU", "GASREGW", "DHHNGSP",
)


class FREDFetcher(BaseMacroFetcher):
    """Macro fetcher backed by pandas-datareader / FRED.

    A FRED API key (env var ``FRED_API_KEY``) is optional but recommended.
    Without one, pandas-datareader falls back to public scraping with
    stricter rate limits — RateLimitManager is configured accordingly.
    """

    def __init__(
        self,
        rate_limiter: RateLimitManager | None = None,
        cleaner: DataCleaner | None = None,
        dual_writer: DualWriter | None = None,
        quality_repo: QualityReportRepository | None = None,
        api_key: str | None = None,
    ) -> None:
        super().__init__(
            source=DataSource.FRED,
            rate_limiter=rate_limiter,
            cleaner=cleaner,
            dual_writer=dual_writer,
            quality_repo=quality_repo,
        )
        # Regola 15: API key da .env, mai hardcoded
        self._api_key: str | None = api_key or os.getenv("FRED_API_KEY")

    async def _fetch_raw_macro(
        self,
        series_id: str,
        start: datetime | None,
        end: datetime | None,
    ) -> pd.DataFrame:
        """Pull a single FRED series. The base class handles cleaning + persistence."""
        try:
            raw = await asyncio.to_thread(
                self._download_sync, series_id, start, end
            )
        except FetchError:
            raise
        except Exception as exc:
            raise FetchError(
                source=self.source,
                detail=f"FRED error for series '{series_id}': {exc}",
            ) from exc

        if raw is None or raw.empty:
            log.warning("fred.empty_response", series_id=series_id)
            return pd.DataFrame()

        return self._normalize_fred_frame(raw, series_id)

    def _download_sync(
        self,
        series_id: str,
        start: datetime | None,
        end: datetime | None,
    ) -> pd.DataFrame | None:
        """Sync wrapper around pandas_datareader.DataReader."""
        # Import locale: facoltativo per i test mock
        from pandas_datareader import data as pdr

        # FRED accetta date naive in pandas-datareader (interprete come UTC)
        start_dt = ensure_utc(start).date() if start else None
        end_dt = ensure_utc(end).date() if end else None

        # api_key è positional in alcune versioni; passiamo via kwarg per portabilità
        kwargs: dict[str, object] = {"name": series_id, "data_source": "fred"}
        if start_dt is not None:
            kwargs["start"] = start_dt
        if end_dt is not None:
            kwargs["end"] = end_dt
        if self._api_key:
            kwargs["api_key"] = self._api_key

        return pdr.DataReader(**kwargs)

    @staticmethod
    def _normalize_fred_frame(raw: pd.DataFrame, series_id: str) -> pd.DataFrame:
        """Convert pandas-datareader output to our canonical macro schema.

        pandas-datareader returns a single-column DataFrame with the series
        name as column header and a DatetimeIndex (often tz-naive).
        """
        df = raw.reset_index()

        # La colonna timestamp di pandas-datareader è tipicamente "DATE"
        ts_col = next(
            (c for c in df.columns if str(c).upper() in ("DATE", "DATETIME")),
            df.columns[0],
        )

        # La colonna valore è quella restante (o quella nominata come series_id)
        value_col_candidates = [c for c in df.columns if c != ts_col]
        if not value_col_candidates:
            raise FetchError(
                source="fred",
                detail=f"unexpected FRED frame for {series_id}: {list(df.columns)}",
            )
        value_col = value_col_candidates[0]

        # Force UTC tz-aware (Regola 19)
        ts_series = pd.to_datetime(df[ts_col])
        if ts_series.dt.tz is None:
            ts_series = ts_series.dt.tz_localize("UTC")
        else:
            ts_series = ts_series.dt.tz_convert("UTC")

        out = pd.DataFrame(
            {
                "ts": ts_series,
                # FRED a volte espone "." per dati non rilasciati: errors="coerce" → NaN
                "value": pd.to_numeric(df[value_col], errors="coerce").astype("float64"),
            }
        )
        return out.reset_index(drop=True)
