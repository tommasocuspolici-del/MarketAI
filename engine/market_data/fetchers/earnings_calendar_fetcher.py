"""Earnings Calendar Fetcher — scarica date e stime utili da yfinance.

Dati raccolti per ticker:
  report_date      data di pubblicazione risultati
  report_time      BMO (Before Market Open) / AMC (After Market Close) / TNS
  eps_estimate     stima consensus EPS
  revenue_estimate stima consensus Revenue
  eps_actual       EPS effettivo (se già pubblicato)
  revenue_actual   Revenue effettivo (se già pubblicato)
  eps_surprise_pct sorpresa EPS in percentuale
  fiscal_period    es. "Q1 2026"

Fonte: yfinance.Ticker.calendar + yfinance.Ticker.earnings_dates
— gratuito, nessuna API key richiesta.

Regola 12: solo fetch→persist qui, nessuna analisi inline.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING

import pandas as pd

from shared.resilience.error_policy import apply_error_policy

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
log = logging.getLogger(__name__)

_TABLE = "earnings_calendar"

# Finestra forward: quanti giorni nel futuro caricare
_FORWARD_DAYS = 90
# Finestra backward: quanti giorni nel passato caricare (per sorprese storiche)
_BACKWARD_DAYS = 365


class EarningsCalendarFetcher:
    """Scarica e persiste dati calendario utili da yfinance.

    Args:
        client: DuckDBClient per la persistenza.
    """

    def __init__(self, client: DuckDBClient) -> None:
        self._client = client

    def fetch_and_persist(self, tickers: list[str]) -> int:
        """Scarica calendario utili per la lista di ticker e persiste.

        Args:
            tickers: Lista di ticker Yahoo Finance (es. ["AAPL", "NVDA"]).

        Returns:
            Numero totale di righe inserite/aggiornate.
        """
        total = 0
        for ticker in tickers:
            n = self._fetch_ticker(ticker)
            total += n
            log.debug("earnings_calendar_fetcher.ticker_done ticker=%s rows=%d", ticker, n)
        log.info("earnings_calendar_fetcher.done total_rows=%d tickers=%d", total, len(tickers))
        return total

    @apply_error_policy(level="RECOVER", fallback=0, context="EarningsCalendarFetcher._fetch_ticker")
    def _fetch_ticker(self, ticker: str) -> int:
        import yfinance as yf

        t = yf.Ticker(ticker)
        company_name = _safe_company_name(t)

        rows: list[dict] = []
        rows.extend(_parse_calendar(t, ticker, company_name))
        rows.extend(_parse_earnings_dates(t, ticker, company_name))

        if not rows:
            log.debug("earnings_calendar_fetcher.no_data ticker=%s", ticker)
            return 0

        df = _deduplicate(pd.DataFrame(rows))
        _validate(df)
        return self._persist(df)

    def get_upcoming(self, days: int = 7) -> pd.DataFrame:
        """Legge gli utili prossimi entro N giorni da oggi."""
        cutoff_start = date.today()
        cutoff_end = cutoff_start + timedelta(days=days)
        try:
            rows = self._client.query(
                f"SELECT ticker, company_name, report_date, report_time, "
                f"eps_estimate, revenue_estimate, eps_actual, revenue_actual, "
                f"eps_surprise_pct, fiscal_period "
                f"FROM {_TABLE} "
                f"WHERE report_date >= ? AND report_date <= ? "
                f"ORDER BY report_date, ticker",
                [cutoff_start, cutoff_end],
            )
            cols = ["ticker", "company_name", "report_date", "report_time",
                    "eps_estimate", "revenue_estimate", "eps_actual", "revenue_actual",
                    "eps_surprise_pct", "fiscal_period"]
            return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)
        except Exception as exc:
            log.warning("earnings_calendar_fetcher.get_upcoming_failed: %s", str(exc)[:120])
            return pd.DataFrame()

    def get_historical(self, ticker: str, lookback_days: int = 365) -> pd.DataFrame:
        """Legge gli utili storici di un ticker."""
        cutoff = date.today() - timedelta(days=lookback_days)
        try:
            rows = self._client.query(
                f"SELECT ticker, company_name, report_date, report_time, "
                f"eps_estimate, revenue_estimate, eps_actual, revenue_actual, "
                f"eps_surprise_pct, revenue_surprise_pct, fiscal_period "
                f"FROM {_TABLE} "
                f"WHERE ticker = ? AND report_date >= ? "
                f"ORDER BY report_date DESC",
                [ticker, cutoff],
            )
            cols = ["ticker", "company_name", "report_date", "report_time",
                    "eps_estimate", "revenue_estimate", "eps_actual", "revenue_actual",
                    "eps_surprise_pct", "revenue_surprise_pct", "fiscal_period"]
            return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)
        except Exception as exc:
            log.warning("earnings_calendar_fetcher.get_historical_failed ticker=%s: %s",
                        ticker, str(exc)[:120])
            return pd.DataFrame()

    # ─── Internal helpers ─────────────────────────────────────────────────────

    def _persist(self, df: pd.DataFrame) -> int:
        n = 0
        for _, row in df.iterrows():
            report_date = row.get("report_date")
            if report_date is None or (hasattr(report_date, "__float__") and pd.isna(report_date)):
                continue
            if isinstance(report_date, pd.Timestamp):
                report_date = report_date.date()

            try:
                self._client.execute(
                    f"""
                    INSERT INTO {_TABLE}
                        (ticker, company_name, report_date, report_time,
                         eps_estimate, revenue_estimate,
                         eps_actual, revenue_actual,
                         eps_surprise_pct, revenue_surprise_pct,
                         fiscal_period, source, fetched_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,'yfinance',NOW())
                    ON CONFLICT (ticker, report_date) DO UPDATE SET
                        company_name=excluded.company_name,
                        report_time=excluded.report_time,
                        eps_estimate=COALESCE(excluded.eps_estimate, earnings_calendar.eps_estimate),
                        revenue_estimate=COALESCE(excluded.revenue_estimate, earnings_calendar.revenue_estimate),
                        eps_actual=COALESCE(excluded.eps_actual, earnings_calendar.eps_actual),
                        revenue_actual=COALESCE(excluded.revenue_actual, earnings_calendar.revenue_actual),
                        eps_surprise_pct=COALESCE(excluded.eps_surprise_pct, earnings_calendar.eps_surprise_pct),
                        revenue_surprise_pct=COALESCE(excluded.revenue_surprise_pct, earnings_calendar.revenue_surprise_pct),
                        fiscal_period=COALESCE(excluded.fiscal_period, earnings_calendar.fiscal_period),
                        fetched_at=NOW()
                    """,
                    [
                        str(row.get("ticker", "")),
                        _str_or_none(row.get("company_name")),
                        report_date,
                        _str_or_none(row.get("report_time")),
                        _float_or_none(row.get("eps_estimate")),
                        _float_or_none(row.get("revenue_estimate")),
                        _float_or_none(row.get("eps_actual")),
                        _float_or_none(row.get("revenue_actual")),
                        _float_or_none(row.get("eps_surprise_pct")),
                        _float_or_none(row.get("revenue_surprise_pct")),
                        _str_or_none(row.get("fiscal_period")),
                    ],
                )
                n += 1
            except Exception as exc:
                log.debug("earnings_calendar_fetcher.persist_row_failed ticker=%s: %s",
                          row.get("ticker"), str(exc)[:80])
        return n


# ─── Parse helpers ────────────────────────────────────────────────────────────

def _safe_company_name(ticker_obj) -> str | None:
    try:
        info = ticker_obj.info
        return info.get("shortName") or info.get("longName")
    except Exception:
        return None


def _parse_calendar(ticker_obj, ticker: str, company_name: str | None) -> list[dict]:
    """Legge ticker.calendar (prossima data utili + stime)."""
    try:
        cal = ticker_obj.calendar
    except Exception:
        return []

    if cal is None:
        return []

    # yfinance >= 0.2.x restituisce un dict
    if isinstance(cal, dict):
        report_date = _extract_date(cal.get("Earnings Date"))
        if report_date is None:
            return []
        return [{
            "ticker": ticker,
            "company_name": company_name,
            "report_date": report_date,
            "report_time": None,
            "eps_estimate": _float_or_none(cal.get("Earnings Average")),
            "revenue_estimate": _float_or_none(cal.get("Revenue Average")),
            "eps_actual": None,
            "revenue_actual": None,
            "eps_surprise_pct": None,
            "revenue_surprise_pct": None,
            "fiscal_period": None,
        }]

    # Vecchie versioni restituivano un DataFrame
    if isinstance(cal, pd.DataFrame):
        rows = []
        for col in cal.columns:
            val = cal.get(col)
            if val is None:
                continue
            d = _extract_date(val.get("Earnings Date") if hasattr(val, "get") else None)
            if d:
                rows.append({
                    "ticker": ticker,
                    "company_name": company_name,
                    "report_date": d,
                    "report_time": None,
                    "eps_estimate": None,
                    "revenue_estimate": None,
                    "eps_actual": None,
                    "revenue_actual": None,
                    "eps_surprise_pct": None,
                    "revenue_surprise_pct": None,
                    "fiscal_period": None,
                })
        return rows

    return []


def _parse_earnings_dates(ticker_obj, ticker: str, company_name: str | None) -> list[dict]:
    """Legge ticker.earnings_dates (storico + forward con stime/sorprese)."""
    try:
        df = ticker_obj.earnings_dates
    except Exception:
        return []

    if df is None or df.empty:
        return []

    cutoff_past = date.today() - timedelta(days=_BACKWARD_DAYS)
    cutoff_future = date.today() + timedelta(days=_FORWARD_DAYS)

    rows = []
    for idx, row in df.iterrows():
        try:
            if isinstance(idx, pd.Timestamp):
                report_date = idx.date()
            else:
                report_date = pd.Timestamp(idx).date()
        except Exception:
            continue

        if report_date < cutoff_past or report_date > cutoff_future:
            continue

        eps_est = _float_or_none(row.get("EPS Estimate"))
        eps_act = _float_or_none(row.get("Reported EPS"))
        surprise_pct = _float_or_none(row.get("Surprise(%)"))

        rows.append({
            "ticker": ticker,
            "company_name": company_name,
            "report_date": report_date,
            "report_time": None,
            "eps_estimate": eps_est,
            "revenue_estimate": None,
            "eps_actual": eps_act,
            "revenue_actual": None,
            "eps_surprise_pct": surprise_pct,
            "revenue_surprise_pct": None,
            "fiscal_period": None,
        })

    return rows


def _deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    """Mantiene la riga più completa per ogni (ticker, report_date)."""
    if df.empty:
        return df
    # Conta campi non-null per riga, mantiene quella con più dati
    df = df.copy()
    df["_completeness"] = df.notna().sum(axis=1)
    df = (df
          .sort_values("_completeness", ascending=False)
          .drop_duplicates(subset=["ticker", "report_date"])
          .drop(columns=["_completeness"]))
    return df


def _validate(df: pd.DataFrame) -> None:
    """Validazione leggera pre-persist (Regola 9)."""
    required = {"ticker", "report_date"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"EarningsCalendar: colonne mancanti {missing}")
    if df["ticker"].isna().any():
        raise ValueError("EarningsCalendar: ticker non può essere null")
    if df["report_date"].isna().any():
        raise ValueError("EarningsCalendar: report_date non può essere null")


# ─── Type coercion helpers ────────────────────────────────────────────────────

def _float_or_none(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def _str_or_none(val) -> str | None:
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    return str(val) if val else None


def _extract_date(val) -> date | None:
    if val is None:
        return None
    # pd.Timestamp is a subclass of datetime/date — check it first
    if isinstance(val, pd.Timestamp):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, list) and val:
        return _extract_date(val[0])
    try:
        return pd.Timestamp(val).date()
    except Exception:
        return None
