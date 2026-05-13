"""FundamentalsRepository — persistence layer for fundamental data.

Handles two DuckDB tables created by migration 011:
  · ``fundamentals_edgar``     — income statement + balance sheet from SEC XBRL
  · ``fundamentals_valuation`` — valuation ratios from Alpha Vantage

Regola 13: dati analitici massivi → DuckDB (non SQLite).
Regola 27: lo schema è creato dalla migration 20260901_011_fundamentals_edgar.sql.
Regola 12: write pipeline = clean → validate types → duckdb_write.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from shared.db.duckdb_client import DuckDBClient, get_duckdb_client
from shared.exceptions import DatabaseError
from shared.logger import get_logger

if TYPE_CHECKING:
    pass

__version__ = "9.0.0"
__all__ = [
    "FundamentalsRepository",
    "get_fundamentals_repository",
    "reset_fundamentals_repository",
]

log = get_logger(__name__)

# Colonne obbligatorie per ciascuna tabella (Regola 9: schema esplicito)
_EDGAR_REQUIRED_COLS: frozenset[str] = frozenset(
    {"ticker", "report_date", "period"}
)
_EDGAR_INCOME_COLS: list[str] = [
    "ticker", "report_date", "period",
    "revenue", "gross_profit", "ebit", "net_income", "eps_diluted",
]
_EDGAR_BALANCE_COLS: list[str] = [
    "ticker", "report_date", "period",
    "total_assets", "total_debt", "equity", "fcf",
]
_EDGAR_ALL_COLS: list[str] = list(
    dict.fromkeys(_EDGAR_INCOME_COLS + _EDGAR_BALANCE_COLS)
)

_VALUATION_REQUIRED_COLS: frozenset[str] = frozenset({"ticker", "computed_at"})
_VALUATION_COLS: list[str] = [
    "ticker", "computed_at",
    "pe_ttm", "pe_forward", "pb", "ps", "ev_ebitda",
    "dividend_yield", "payout_ratio", "beta", "market_cap", "source",
]


class FundamentalsRepository:
    """CRUD for ``fundamentals_edgar`` and ``fundamentals_valuation`` DuckDB tables.

    Thread-safe: ogni operazione apre la propria transazione DuckDB.
    Non è un singleton: istanziare dove necessario o usare get_fundamentals_repository().
    """

    def __init__(self, client: DuckDBClient | None = None) -> None:
        self._client = client or get_duckdb_client()

    # ─── EDGAR — Write ────────────────────────────────────────────────────────

    def write_edgar(self, df: pd.DataFrame) -> int:
        """Upsert income statement + balance sheet rows into fundamentals_edgar.

        Args:
            df: DataFrame with at least columns in _EDGAR_REQUIRED_COLS.
                Extra columns outside _EDGAR_ALL_COLS are silently dropped.

        Returns:
            Number of rows upserted.

        Raises:
            DatabaseError: On DuckDB errors.
            ValueError: If required columns are missing.
        """
        if df.empty:
            return 0

        # Valida colonne obbligatorie
        missing = _EDGAR_REQUIRED_COLS - set(df.columns)
        if missing:
            raise ValueError(f"fundamentals_edgar: missing required columns {missing}")

        prepared = self._prepare_edgar_df(df)
        if prepared.empty:
            return 0

        try:
            with self._client.transaction() as conn:
                # ANTI-REGRESSIONE (B3 v7.2.0): usa INSERT OR REPLACE per evitare
                # il DuckDB Constraint Error che si verifica con DELETE + INSERT
                # nella stessa transazione MVCC.
                #
                # ANTI-REGRESSIONE (v9.0 Sett.1 — BUG CORRETTO):
                # DuckDB non permette di referenziare un alias di colonna nella
                # stessa SELECT in cui è definito (Binder Error: "Column X
                # referenced that exists in the SELECT clause - but cannot be
                # referenced before it is defined").
                # Soluzione: usare CASE WHEN invece di COALESCE su colonne con alias,
                # o elencare esplicitamente le colonne nella INSERT target list.
                conn.register("_edgar_batch", prepared)
                conn.execute("""
                    INSERT OR REPLACE INTO fundamentals_edgar
                    (ticker, report_date, period, revenue, gross_profit, ebit,
                     net_income, eps_diluted, total_assets, total_debt, equity,
                     fcf, source, fetched_at)
                    SELECT
                        ticker, report_date, period,
                        revenue, gross_profit, ebit, net_income, eps_diluted,
                        total_assets, total_debt, equity, fcf,
                        'edgar_xbrl',
                        NOW()
                    FROM _edgar_batch
                """)
                n = len(prepared)

            log.info(
                "fundamentals_repo.edgar_written",
                rows=n,
                tickers=prepared["ticker"].nunique(),
            )
            return n

        except Exception as exc:
            raise DatabaseError(f"fundamentals_edgar write failed: {exc}") from exc

    # ─── EDGAR — Read ─────────────────────────────────────────────────────────

    def read_income(
        self,
        ticker: str,
        limit: int = 8,  # 8 quarter = 2 anni
    ) -> pd.DataFrame:
        """Read income statement rows for a ticker, newest first.

        Args:
            ticker: Equity ticker.
            limit: Maximum number of rows to return.

        Returns:
            DataFrame with income statement columns, or empty if none found.
        """
        cols = "ticker, report_date, period, revenue, gross_profit, ebit, net_income, eps_diluted"
        try:
            with self._client.transaction() as conn:
                df = conn.execute(
                    f"""
                    SELECT {cols}
                    FROM fundamentals_edgar
                    WHERE ticker = ?
                    ORDER BY report_date DESC
                    LIMIT ?
                    """,
                    [ticker, limit],
                ).df()
            return df
        except Exception as exc:
            log.warning("fundamentals_repo.read_income_error", ticker=ticker, error=str(exc))
            return pd.DataFrame()

    def read_balance_sheet(
        self,
        ticker: str,
        limit: int = 8,
    ) -> pd.DataFrame:
        """Read balance sheet rows for a ticker, newest first."""
        cols = "ticker, report_date, period, total_assets, total_debt, equity, fcf"
        try:
            with self._client.transaction() as conn:
                df = conn.execute(
                    f"""
                    SELECT {cols}
                    FROM fundamentals_edgar
                    WHERE ticker = ?
                    ORDER BY report_date DESC
                    LIMIT ?
                    """,
                    [ticker, limit],
                ).df()
            return df
        except Exception as exc:
            log.warning("fundamentals_repo.read_balance_error", ticker=ticker, error=str(exc))
            return pd.DataFrame()

    def read_latest_edgar(self, ticker: str) -> dict[str, object] | None:
        """Return the most recent fundamentals_edgar row as a dict, or None."""
        try:
            with self._client.transaction() as conn:
                result = conn.execute(
                    """
                    SELECT *
                    FROM fundamentals_edgar
                    WHERE ticker = ?
                    ORDER BY report_date DESC
                    LIMIT 1
                    """,
                    [ticker],
                ).fetchone()
            if result is None:
                return None
            # Converte in dict con column names
            cols = conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'fundamentals_edgar'"
            ).fetchall()
            return dict(zip([c[0] for c in cols], result))
        except Exception as exc:
            log.warning("fundamentals_repo.read_latest_edgar_error", ticker=ticker, error=str(exc))
            return None

    # ─── VALUATION — Write ────────────────────────────────────────────────────

    def write_valuation(self, df: pd.DataFrame) -> int:
        """Upsert valuation ratio rows into fundamentals_valuation.

        Args:
            df: DataFrame with at least columns in _VALUATION_REQUIRED_COLS.

        Returns:
            Number of rows upserted.
        """
        if df.empty:
            return 0

        missing = _VALUATION_REQUIRED_COLS - set(df.columns)
        if missing:
            raise ValueError(f"fundamentals_valuation: missing required columns {missing}")

        prepared = self._prepare_valuation_df(df)
        if prepared.empty:
            return 0

        try:
            with self._client.transaction() as conn:
                conn.register("_valuation_batch", prepared)
                # ANTI-REGRESSIONE (v9.0 Sett.1): write_valuation include "source"
                # in _VALUATION_COLS quindi la colonna è nel batch.
                # Usa literal 'alpha_vantage' come fallback sicuro per evitare
                # qualsiasi ambiguità DuckDB con alias nelle SELECT.
                conn.execute("""
                    INSERT OR REPLACE INTO fundamentals_valuation
                    (ticker, computed_at, pe_ttm, pe_forward, pb, ps, ev_ebitda,
                     dividend_yield, payout_ratio, beta, market_cap, source, fetched_at)
                    SELECT
                        ticker, computed_at,
                        pe_ttm, pe_forward, pb, ps, ev_ebitda,
                        dividend_yield, payout_ratio, beta, market_cap,
                        'alpha_vantage',
                        NOW()
                    FROM _valuation_batch
                """)
                n = len(prepared)

            log.info(
                "fundamentals_repo.valuation_written",
                rows=n,
                tickers=prepared["ticker"].nunique(),
            )
            return n

        except Exception as exc:
            raise DatabaseError(f"fundamentals_valuation write failed: {exc}") from exc

    # ─── VALUATION — Read ─────────────────────────────────────────────────────

    def read_valuation(self, ticker: str) -> pd.DataFrame:
        """Return all valuation rows for a ticker, newest first.

        Utile per visualizzare trend P/E nel tempo.
        """
        try:
            with self._client.transaction() as conn:
                df = conn.execute(
                    """
                    SELECT ticker, computed_at, pe_ttm, pe_forward, pb, ps,
                           ev_ebitda, dividend_yield, payout_ratio, beta, market_cap
                    FROM fundamentals_valuation
                    WHERE ticker = ?
                    ORDER BY computed_at DESC
                    LIMIT 52
                    """,
                    [ticker],
                ).df()
            return df
        except Exception as exc:
            log.warning("fundamentals_repo.read_valuation_error", ticker=ticker, error=str(exc))
            return pd.DataFrame()

    def read_latest_valuation(self, ticker: str) -> dict[str, object] | None:
        """Return the most recent valuation row as a dict, or None.

        Uso tipico: card P/E nella pagina K2 (Equity).
        """
        df = self.read_valuation(ticker)
        if df.empty:
            return None
        return df.iloc[0].to_dict()

    def read_pe_ratio(self, ticker: str) -> float | None:
        """Return the most recent P/E TTM for quick display, or None."""
        row = self.read_latest_valuation(ticker)
        if row is None:
            return None
        val = row.get("pe_ttm")
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return None
        return float(val)

    # ─── Helpers di preparazione DataFrame ───────────────────────────────────

    @staticmethod
    def _prepare_edgar_df(df: pd.DataFrame) -> pd.DataFrame:
        """Coerce types and fill missing columns for fundamentals_edgar."""
        # Aggiunge colonne mancanti con NaN
        for col in _EDGAR_ALL_COLS:
            if col not in df.columns:
                df[col] = np.nan

        # Filtra alle sole colonne della tabella
        available = [c for c in _EDGAR_ALL_COLS if c in df.columns]
        prepared = df[available].copy()

        # Regola 19: report_date deve essere tz-aware UTC
        if "report_date" in prepared.columns:
            prepared["report_date"] = pd.to_datetime(
                prepared["report_date"], utc=True, errors="coerce"
            )
        # Drop righe con chiave mancante
        prepared = prepared.dropna(subset=list(_EDGAR_REQUIRED_COLS))

        # Cast numerici float64 (Regola 8)
        numeric_cols = [
            c for c in prepared.columns
            if c not in ("ticker", "period", "source")
            and c != "report_date"
        ]
        for col in numeric_cols:
            prepared[col] = pd.to_numeric(prepared[col], errors="coerce").astype("float64")

        return prepared

    @staticmethod
    def _prepare_valuation_df(df: pd.DataFrame) -> pd.DataFrame:
        """Coerce types and fill missing columns for fundamentals_valuation."""
        for col in _VALUATION_COLS:
            if col not in df.columns:
                df[col] = np.nan if col not in ("ticker", "source") else "alpha_vantage"

        available = [c for c in _VALUATION_COLS if c in df.columns]
        prepared = df[available].copy()

        if "computed_at" in prepared.columns:
            prepared["computed_at"] = pd.to_datetime(
                prepared["computed_at"], utc=True, errors="coerce"
            )
        prepared = prepared.dropna(subset=list(_VALUATION_REQUIRED_COLS))

        numeric_cols = [
            c for c in prepared.columns
            if c not in ("ticker", "source") and c != "computed_at"
        ]
        for col in numeric_cols:
            prepared[col] = pd.to_numeric(prepared[col], errors="coerce").astype("float64")

        return prepared


# ─── Singleton thread-safe ────────────────────────────────────────────────────
# Stessa strategia di get_macro_repository() (Regola conforme)

_repo_lock = threading.Lock()
_default_repo: FundamentalsRepository | None = None


def get_fundamentals_repository() -> FundamentalsRepository:
    """Return (or create) the singleton FundamentalsRepository."""
    global _default_repo
    with _repo_lock:
        if _default_repo is None:
            _default_repo = FundamentalsRepository()
        return _default_repo


def reset_fundamentals_repository() -> None:
    """Reset singleton — utile per teardown nei test."""
    global _default_repo
    with _repo_lock:
        _default_repo = None
