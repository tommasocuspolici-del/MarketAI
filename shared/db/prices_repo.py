"""Prices repository — OHLCV reads/writes on DuckDB.

Single-responsibility module (Rule 2): all specialized access to the
``prices_ohlcv`` table lives here. The base ``DuckDBClient`` stays generic.

All writes go through ``INSERT OR REPLACE`` to guarantee idempotency on
the composite primary key ``(ticker, exchange, timeframe, ts)``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from shared.db.duckdb_client import DuckDBClient, get_duckdb_client
from shared.db.schemas import validate_ohlcv
from shared.exceptions import DuckDBError
from shared.logger import get_logger
from shared.metrics import metrics
from shared.types import TimeFrame, ensure_utc

if TYPE_CHECKING:
    from datetime import datetime

    from shared.types import Currency

__version__ = "6.0.0"

__all__ = ["PricesRepository", "get_prices_repository"]

log = get_logger(__name__)

_TABLE = "prices_ohlcv"


class PricesRepository:
    """Specialized OHLCV access on DuckDB."""

    def __init__(self, client: DuckDBClient | None = None) -> None:
        self._client = client or get_duckdb_client()

    # ─── Writes ──────────────────────────────────────────────────────────
    def write_ohlcv(
        self,
        ticker: str,
        exchange: str,
        timeframe: TimeFrame | str,
        df: pd.DataFrame,
        source: str,
        currency: Currency | str = "USD",
    ) -> int:
        """Insert or replace OHLCV bars for a single (ticker, exchange, timeframe).

        Args:
            ticker: Instrument symbol (e.g. "AAPL").
            exchange: Exchange code (e.g. "NASDAQ", "MILAN").
            timeframe: Bar timeframe (enum or string like "1d").
            df: DataFrame validated against OHLCV_SCHEMA.
            source: Data provider name (e.g. "yahoo_finance").
            currency: ISO 4217 or Currency enum.

        Returns:
            Number of rows inserted/updated.
        """
        if df.empty:
            return 0

        # Validazione Pandera (Regola 9): rifiuta dati con schema errato
        validated = validate_ohlcv(df)

        tf_str = timeframe.value if isinstance(timeframe, TimeFrame) else timeframe
        currency_str = (
            currency.value if hasattr(currency, "value") else str(currency)
        )

        # Prepariamo il DataFrame con tutte le colonne richieste dalla tabella
        prepared = self._prepare_ohlcv_for_insert(
            validated, ticker, exchange, tf_str, source, currency_str
        )

        n_rows = len(prepared)
        with metrics.timer("duckdb_write_ohlcv_ms", source=source):
            try:
                # Registriamo il DF come vista temporanea, poi upsert idempotente
                self._client.connection.register("__ohlcv_stage__", prepared)
                # INSERT OR REPLACE è la forma supportata da DuckDB per upsert
                # sulle chiavi primarie. Gli aggiornamenti successivi (es. correzioni
                # di splits/dividends) sostituiscono i valori precedenti.
                self._client.execute(
                    f"""
                    INSERT OR REPLACE INTO {_TABLE}
                    SELECT ticker, exchange, timeframe, ts, open, high, low,
                           close, volume, adj_close, currency, source, inserted_at
                    FROM __ohlcv_stage__
                    """
                )
                self._client.connection.unregister("__ohlcv_stage__")
            except DuckDBError:
                # Cleanup best-effort della vista anche in caso di errore
                import contextlib

                with contextlib.suppress(Exception):
                    self._client.connection.unregister("__ohlcv_stage__")
                raise

        metrics.inc("prices_rows_written_total", amount=n_rows, source=source)
        log.info(
            "prices.written",
            ticker=ticker,
            exchange=exchange,
            timeframe=tf_str,
            rows=n_rows,
            source=source,
        )
        return n_rows

    @staticmethod
    def _prepare_ohlcv_for_insert(
        df: pd.DataFrame,
        ticker: str,
        exchange: str,
        timeframe: str,
        source: str,
        currency: str,
    ) -> pd.DataFrame:
        """Build the exact set of columns required by prices_ohlcv."""
        # Copia difensiva: non alteriamo il DataFrame del chiamante
        out = df.copy()
        out["ticker"] = ticker
        out["exchange"] = exchange
        out["timeframe"] = timeframe
        out["currency"] = currency
        out["source"] = source
        # inserted_at gestito dal default della tabella (NOW()); includiamo NaT
        # per rispettare l'ordine colonne della SELECT
        out["inserted_at"] = pd.Timestamp.now(tz="UTC")

        # adj_close è opzionale nel DataFrame di ingresso: se assente, None
        if "adj_close" not in out.columns:
            out["adj_close"] = None

        # Ordine esatto delle colonne come nella tabella DuckDB
        column_order = [
            "ticker",
            "exchange",
            "timeframe",
            "ts",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "adj_close",
            "currency",
            "source",
            "inserted_at",
        ]
        return out[column_order]

    # ─── Reads ───────────────────────────────────────────────────────────
    def read_prices(
        self,
        ticker: str,
        exchange: str | None = None,
        timeframe: TimeFrame | str = TimeFrame.D1,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """Fetch OHLCV bars with optional filters.

        Returns an empty DataFrame if no rows match. The ``ts`` column is
        UTC-aware (Rule 19).
        """
        tf_str = timeframe.value if isinstance(timeframe, TimeFrame) else timeframe

        # Costruzione query dinamica: WHERE sempre presente su ticker,
        # gli altri filtri sono condizionali per massimizzare l'uso dell'indice.
        clauses = ["ticker = ?", "timeframe = ?"]
        params: list[object] = [ticker, tf_str]
        if exchange is not None:
            clauses.append("exchange = ?")
            params.append(exchange)
        if start is not None:
            clauses.append("ts >= ?")
            params.append(ensure_utc(start))
        if end is not None:
            clauses.append("ts <= ?")
            params.append(ensure_utc(end))

        where = " AND ".join(clauses)
        sql = (
            f"SELECT ts, open, high, low, close, volume, adj_close, currency "
            f"FROM {_TABLE} WHERE {where} ORDER BY ts"
        )

        with metrics.timer("duckdb_read_prices_ms"):
            df = self._client.query_df(sql, params)

        return df

    def read_latest_price(
        self,
        ticker: str,
        exchange: str | None = None,
        timeframe: TimeFrame | str = TimeFrame.D1,
    ) -> dict[str, object] | None:
        """Return the most recent bar for a ticker, or None if no data."""
        tf_str = timeframe.value if isinstance(timeframe, TimeFrame) else timeframe
        clauses = ["ticker = ?", "timeframe = ?"]
        params: list[object] = [ticker, tf_str]
        if exchange is not None:
            clauses.append("exchange = ?")
            params.append(exchange)

        where = " AND ".join(clauses)
        sql = (
            f"SELECT ticker, exchange, timeframe, ts, open, high, low, "
            f"close, volume, adj_close, currency "
            f"FROM {_TABLE} WHERE {where} ORDER BY ts DESC LIMIT 1"
        )
        rows = self._client.query(sql, params)
        if not rows:
            return None

        cols = [
            "ticker", "exchange", "timeframe", "ts", "open", "high", "low",
            "close", "volume", "adj_close", "currency",
        ]
        return dict(zip(cols, rows[0], strict=True))

    def count_bars(
        self,
        ticker: str,
        timeframe: TimeFrame | str = TimeFrame.D1,
    ) -> int:
        """Return the number of bars persisted for a ticker+timeframe."""
        tf_str = timeframe.value if isinstance(timeframe, TimeFrame) else timeframe
        rows = self._client.query(
            f"SELECT COUNT(*) FROM {_TABLE} WHERE ticker = ? AND timeframe = ?",
            [ticker, tf_str],
        )
        return int(rows[0][0]) if rows else 0

    # ─── Deletes ─────────────────────────────────────────────────────────
    def delete_prices(
        self,
        ticker: str,
        before_ts: datetime,
        timeframe: TimeFrame | str | None = None,
    ) -> int:
        """Delete bars older than ``before_ts``. Returns the count deleted."""
        clauses = ["ticker = ?", "ts < ?"]
        params: list[object] = [ticker, ensure_utc(before_ts)]
        if timeframe is not None:
            tf_str = timeframe.value if isinstance(timeframe, TimeFrame) else timeframe
            clauses.append("timeframe = ?")
            params.append(tf_str)

        where = " AND ".join(clauses)
        count_rows = self._client.query(
            f"SELECT COUNT(*) FROM {_TABLE} WHERE {where}", params
        )
        count = int(count_rows[0][0]) if count_rows else 0
        if count > 0:
            self._client.execute(f"DELETE FROM {_TABLE} WHERE {where}", params)
            log.info("prices.deleted", ticker=ticker, rows=count)
        return count


# ═══════════════════════════════════════════════════════════════════════════
# Singleton accessor
# ═══════════════════════════════════════════════════════════════════════════
_INSTANCE: PricesRepository | None = None


def get_prices_repository() -> PricesRepository:
    """Return the process-wide PricesRepository singleton."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = PricesRepository()
    return _INSTANCE


def reset_prices_repository() -> None:
    """Reset the singleton (tests only)."""
    global _INSTANCE
    _INSTANCE = None
