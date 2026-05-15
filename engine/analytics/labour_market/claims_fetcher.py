"""Claims Fetcher — scarica dati settimanali ICSA/CCSA/IURSA da FRED.

Serie FRED target:
  ICSA   initial_claims (migliaia, SA, settimanale)
  CCSA   continuing_claims (migliaia, SA)
  IURSA  insured_unemp_rate (%)

Calcoli derivati (post-fetch):
  claims_4wk_ma  = rolling(4).mean() di ICSA
  claims_yoy_pct = (ICSA / ICSA_52w_ago - 1) * 100
  claims_mom_pct = (ICSA / ICSA_4w_ago - 1) * 100

Regola 12: solo fetch→persist qui, nessuna analisi inline.
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

_TABLE = "claims_cycle"

_FRED_ICSA  = "ICSA"   # Initial Claims (SA, weekly)
_FRED_CCSA  = "CCSA"   # Continuing Claims (SA)
_FRED_IURSA = "IURSA"  # Insured Unemployment Rate (SA)

_ROLLING_WINDOW   = 4   # settimane per 4wk MA
_YOY_LAG_WEEKS    = 52  # lag year-over-year
_MOM_LAG_WEEKS    = 4   # lag month-over-month (4 settimane)

# Soglie regime Claims (migliaia) — calibrate su dati 1970-2025
_THRESHOLD_EXPANSION   = 300_000  # < 300K → expansion
_THRESHOLD_PEAK        = 350_000  # 300-350K → peak
_THRESHOLD_CONTRACTION = 400_000  # > 400K → contraction (< trough if declining)

_MAX_OBS = 1200  # ~23 anni settimanali


class ClaimsFetcher:
    """Scarica e persiste dati settimanali Claims da FRED.

    Args:
        client:      DuckDBClient per la persistenza.
        fred_client: FredSimpleClient per le chiamate API FRED.
    """

    def __init__(self, client: DuckDBClient, fred_client: FredSimpleClient) -> None:
        self._client = client
        self._fred = fred_client

    def fetch_and_persist(self, lookback_years: int = 20) -> int:
        """Scarica serie Claims da FRED e persiste in claims_cycle.

        Args:
            lookback_years: Anni di storia da caricare.

        Returns:
            Numero di righe inserite/aggiornate.
        """
        start = date.today() - timedelta(days=lookback_years * 365)
        limit = lookback_years * 55  # margine per dati settimanali

        icsa_df  = self._fetch_series(_FRED_ICSA,  start, limit)
        ccsa_df  = self._fetch_series(_FRED_CCSA,  start, limit)
        iursa_df = self._fetch_series(_FRED_IURSA, start, limit)

        if icsa_df is None or icsa_df.empty:
            log.warning("claims_fetcher.icsa_unavailable")
            return 0

        icsa = icsa_df.set_index("ts")["value"].sort_index().rename("initial_claims")
        ccsa  = (ccsa_df.set_index("ts")["value"].sort_index()
                 if ccsa_df is not None and not ccsa_df.empty else pd.Series(dtype=float))
        iursa = (iursa_df.set_index("ts")["value"].sort_index()
                 if iursa_df is not None and not iursa_df.empty else pd.Series(dtype=float))

        # Derived series
        ma4  = icsa.rolling(_ROLLING_WINDOW, min_periods=2).mean()
        yoy  = (icsa / icsa.shift(_YOY_LAG_WEEKS) - 1.0) * 100.0
        mom  = (icsa / icsa.shift(_MOM_LAG_WEEKS)  - 1.0) * 100.0

        df = pd.DataFrame({
            "week_ending":      icsa.index,
            "initial_claims":   icsa.values,
            "continuing_claims": ccsa.reindex(icsa.index).values,
            "insured_unemp_rate": iursa.reindex(icsa.index).values,
            "claims_4wk_ma":    ma4.values,
            "claims_yoy_pct":   yoy.values,
            "claims_mom_pct":   mom.values,
        })

        n = self._persist(df)
        log.info("claims_fetcher.done rows=%d lookback_years=%d", n, lookback_years)
        return n

    def get_latest(self, lookback_weeks: int = 104) -> pd.DataFrame:
        """Legge le ultime N settimane da claims_cycle."""
        cutoff = date.today() - timedelta(weeks=lookback_weeks)
        try:
            rows = self._client.query(
                f"SELECT week_ending, initial_claims, continuing_claims, "
                f"insured_unemp_rate, claims_4wk_ma, claims_yoy_pct, claims_mom_pct, "
                f"cycle_regime, signal_strength "
                f"FROM {_TABLE} WHERE week_ending >= ? ORDER BY week_ending",
                [cutoff],
            )
            cols = ["week_ending", "initial_claims", "continuing_claims",
                    "insured_unemp_rate", "claims_4wk_ma", "claims_yoy_pct",
                    "claims_mom_pct", "cycle_regime", "signal_strength"]
            return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)
        except Exception as exc:
            log.warning("claims_fetcher.get_latest_failed: %s", str(exc)[:120])
            return pd.DataFrame()

    # ─── Internal helpers ─────────────────────────────────────────────────

    @apply_error_policy(level="RECOVER", fallback=None, context="ClaimsFetcher._fetch_series")
    def _fetch_series(self, series_id: str, start: date, limit: int) -> pd.DataFrame | None:
        df = self._fred.fetch_series(
            series_id, start=start, limit=limit, sort_order="asc"
        )
        df = df.dropna(subset=["value"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        return df.dropna(subset=["value"])

    def _persist(self, df: pd.DataFrame) -> int:
        n = 0
        for _, row in df.iterrows():
            week_ending = row["week_ending"]
            if pd.isna(week_ending):
                continue
            if isinstance(week_ending, pd.Timestamp):
                week_ending = week_ending.date()

            ic     = _f(row, "initial_claims")
            cc     = _f(row, "continuing_claims")
            iur    = _f(row, "insured_unemp_rate")
            ma4    = _f(row, "claims_4wk_ma")
            yoy    = _f(row, "claims_yoy_pct")
            mom    = _f(row, "claims_mom_pct")
            regime = _classify_regime(ma4, yoy) if ma4 is not None else None
            signal = _regime_to_signal(regime)

            try:
                self._client.execute(
                    f"""
                    INSERT INTO {_TABLE}
                        (week_ending, initial_claims, continuing_claims,
                         insured_unemp_rate, claims_4wk_ma, claims_yoy_pct,
                         claims_mom_pct, cycle_regime, signal_strength)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT (week_ending) DO UPDATE SET
                        initial_claims=excluded.initial_claims,
                        continuing_claims=excluded.continuing_claims,
                        insured_unemp_rate=excluded.insured_unemp_rate,
                        claims_4wk_ma=excluded.claims_4wk_ma,
                        claims_yoy_pct=excluded.claims_yoy_pct,
                        claims_mom_pct=excluded.claims_mom_pct,
                        cycle_regime=excluded.cycle_regime,
                        signal_strength=excluded.signal_strength,
                        fetched_at=NOW()
                    """,
                    [week_ending, ic, cc, iur, ma4, yoy, mom, regime, signal],
                )
                n += 1
            except Exception as exc:
                log.debug("claims_fetcher.persist_row_failed: %s", str(exc)[:80])
        return n


def _classify_regime(ma4: float | None, yoy: float | None) -> str:
    """Classifica il regime settimanale in base a 4wk MA e YoY."""
    if ma4 is None:
        return "unknown"
    if ma4 < _THRESHOLD_EXPANSION and (yoy is None or yoy < 10.0):
        return "expansion"
    if ma4 < _THRESHOLD_PEAK:
        return "peak"
    if ma4 > _THRESHOLD_CONTRACTION:
        return "contraction"
    return "trough"


def _regime_to_signal(regime: str | None) -> float | None:
    _MAP = {
        "expansion":   0.7,
        "peak":        0.1,
        "trough":     -0.3,
        "contraction": -0.8,
    }
    return _MAP.get(regime or "", None)


def _f(row: pd.Series, col: str) -> float | None:
    val = row.get(col)
    if val is None or (hasattr(val, "__float__") and pd.isna(val)):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
