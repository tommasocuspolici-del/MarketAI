"""Registry persistito per la mappatura instrument_id → ticker reale.

Sostituisce il dict _INSTRUMENT_ID_TO_REAL_TICKER hardcoded in etoro_importer.py
con un lookup persistito su DuckDB (tabella instrument_registry).

Priorità lookup (dalla più alla meno fidato):
  1. user_override  — impostato dall'utente nella UI
  2. manual         — seed verificato da roadmap
  3. api_auto       — risolto automaticamente via /instruments endpoint

ROADMAP_CODE_QUALITY_v1.0 — Blocco B, Settimana 4 (P3 — Critica).

Uso::

    from engine.market_data.instrument_registry import InstrumentRegistry

    registry = InstrumentRegistry()
    ticker = registry.get_ticker(3040)   # → "SWDA.L"

Test: tests/engine/test_instrument_registry.py
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from shared.db.duckdb_client import DuckDBClient, get_duckdb_client
from shared.exceptions import DuckDBError

__version__ = "8.1.0"

__all__ = ["InstrumentMapping", "InstrumentRegistry"]

log = logging.getLogger(__name__)

_TABLE = "instrument_registry"

_SELECT_COLS = (
    "instrument_id, real_ticker, display_name, native_currency, "
    "exchange, isin, source, confidence"
)


@dataclass(frozen=True, slots=True)
class InstrumentMapping:
    """Mapping verificato tra un instrument_id eToro e il ticker Yahoo Finance."""

    instrument_id: int
    real_ticker: str
    display_name: str | None
    native_currency: str
    exchange: str | None
    isin: str | None
    source: str
    confidence: float


# Fallback hardcoded dei 5 mapping storici (identici al seed della migration 017).
# Usato quando DuckDB non è raggiungibile o il file è corrotto.
_SEED_FALLBACK: dict[int, InstrumentMapping] = {
    3040:  InstrumentMapping(3040,  "SWDA.L",  "iShares Core MSCI World UCITS ETF",  "GBX", "LSE",   "IE00B4L5Y983", "manual", 1.0),
    3434:  InstrumentMapping(3434,  "CSPX.L",  "iShares Core S&P 500 UCITS ETF",     "GBX", "LSE",   "IE00B5BMR087", "manual", 1.0),
    15435: InstrumentMapping(15435, "EIMI.L",  "iShares Core MSCI EM IMI UCITS ETF", "GBX", "LSE",   "IE00BKM4GZ66", "manual", 1.0),
    3394:  InstrumentMapping(3394,  "EUN5.DE", "iShares EUR Corp Bond UCITS ETF",     "EUR", "XETRA", "IE00B3F81R35", "manual", 1.0),
    10569: InstrumentMapping(10569, "IBCN.DE", "iShares EUR Govt Bond 3-7yr UCITS",  "EUR", "XETRA", "IE00B3VTML14", "manual", 1.0),
}


class InstrumentRegistry:
    """Lookup e aggiornamento del registry strumenti su DuckDB.

    Accetta un ``DuckDBClient`` opzionale per facilitare i test con DB
    in memoria. In produzione usa il singleton globale ``get_duckdb_client()``.
    """

    def __init__(self, client: DuckDBClient | None = None) -> None:
        self._client = client or get_duckdb_client()

    # ─── Reads ───────────────────────────────────────────────────────────

    def get(self, instrument_id: int) -> InstrumentMapping | None:
        """Restituisce il mapping per un instrument_id, o None se non trovato."""
        sql = (
            f"SELECT {_SELECT_COLS} FROM {_TABLE} "
            "WHERE instrument_id = ? "
            "ORDER BY CASE source "
            "  WHEN 'user_override' THEN 1 "
            "  WHEN 'manual' THEN 2 "
            "  ELSE 3 "
            "END LIMIT 1"
        )
        try:
            rows = self._client.query(sql, [instrument_id])
        except DuckDBError as exc:
            log.error(
                "instrument_registry.get_failed: DB unavailable, seed fallback for %d: %s",
                instrument_id, str(exc)[:120],
            )
            return _SEED_FALLBACK.get(instrument_id)
        if not rows:
            return None
        r = rows[0]
        return InstrumentMapping(
            instrument_id=r[0],
            real_ticker=r[1],
            display_name=r[2],
            native_currency=r[3],
            exchange=r[4],
            isin=r[5],
            source=r[6],
            confidence=r[7],
        )

    def get_ticker(self, instrument_id: int) -> str | None:
        """Convenience: restituisce solo il ticker reale, o None."""
        mapping = self.get(instrument_id)
        return mapping.real_ticker if mapping else None

    def all_ids(self) -> list[int]:
        """Restituisce tutti gli instrument_id presenti nel registry."""
        try:
            rows = self._client.query(f"SELECT instrument_id FROM {_TABLE}")
        except DuckDBError as exc:
            log.warning("instrument_registry.all_ids_failed error=%s", exc)
            return []
        return [r[0] for r in rows]

    def all_mappings(self) -> list[InstrumentMapping]:
        """Restituisce tutti i mapping presenti nel registry."""
        sql = (
            f"SELECT {_SELECT_COLS} FROM {_TABLE} "
            "ORDER BY instrument_id"
        )
        try:
            rows = self._client.query(sql)
        except DuckDBError as exc:
            log.warning("instrument_registry.all_mappings_failed error=%s", exc)
            return []
        return [
            InstrumentMapping(
                instrument_id=r[0],
                real_ticker=r[1],
                display_name=r[2],
                native_currency=r[3],
                exchange=r[4],
                isin=r[5],
                source=r[6],
                confidence=r[7],
            )
            for r in rows
        ]

    # ─── Writes ──────────────────────────────────────────────────────────

    def register_from_api(
        self,
        instrument_id: int,
        real_ticker: str,
        display_name: str | None = None,
        native_currency: str = "USD",
        confidence: float = 0.8,
    ) -> None:
        """Salva un mapping scoperto automaticamente via API eToro.

        Non sovrascrive mapping con source 'manual' o 'user_override': solo
        i mapping 'api_auto' vengono aggiornati da questa funzione.
        """
        sql = f"""
            INSERT INTO {_TABLE}
                (instrument_id, real_ticker, display_name, native_currency,
                 source, confidence)
            VALUES (?, ?, ?, ?, 'api_auto', ?)
            ON CONFLICT (instrument_id) DO UPDATE SET
                real_ticker    = excluded.real_ticker,
                display_name   = excluded.display_name,
                native_currency = excluded.native_currency,
                confidence     = excluded.confidence,
                updated_at     = NOW()
            WHERE {_TABLE}.source = 'api_auto'
        """
        try:
            self._client.execute(
                sql,
                [instrument_id, real_ticker, display_name, native_currency, confidence],
            )
        except DuckDBError as exc:
            log.warning(
                "instrument_registry.register_from_api_failed iid=%s error=%s",
                instrument_id, exc,
            )

    def upsert_manual(
        self,
        instrument_id: int,
        real_ticker: str,
        display_name: str | None = None,
        native_currency: str = "USD",
        exchange: str | None = None,
        isin: str | None = None,
    ) -> None:
        """Inserisce o aggiorna un mapping manuale (source='manual').

        Sovrascrive qualsiasi source precedente (incluso api_auto).
        Usato dall'UI per aggiungere/correggere mapping verificati.
        """
        sql = f"""
            INSERT INTO {_TABLE}
                (instrument_id, real_ticker, display_name, native_currency,
                 exchange, isin, source, confidence)
            VALUES (?, ?, ?, ?, ?, ?, 'manual', 1.0)
            ON CONFLICT (instrument_id) DO UPDATE SET
                real_ticker     = excluded.real_ticker,
                display_name    = excluded.display_name,
                native_currency = excluded.native_currency,
                exchange        = excluded.exchange,
                isin            = excluded.isin,
                source          = 'manual',
                confidence      = 1.0,
                updated_at      = NOW()
        """
        try:
            self._client.execute(
                sql,
                [instrument_id, real_ticker, display_name, native_currency,
                 exchange, isin],
            )
        except DuckDBError as exc:
            log.warning(
                "instrument_registry.upsert_manual_failed iid=%s error=%s",
                instrument_id, exc,
            )
