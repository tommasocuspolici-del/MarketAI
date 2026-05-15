"""Test per engine/market_data/instrument_registry.py.

Coverage target: ≥ 90%.
Rif: ROADMAP_CODE_QUALITY_v1.0, Settimana 4 (DoD).

Tutti i test usano un DuckDBClient in memoria (non toccano il DB reale).
"""
from __future__ import annotations

import duckdb
import pytest

from shared.db.duckdb_client import DuckDBClient
from engine.market_data.instrument_registry import InstrumentMapping, InstrumentRegistry

# ─────────────────────────────────────────────────────────────── fixtures

_DDL = """
CREATE TABLE IF NOT EXISTS instrument_registry (
    instrument_id     INTEGER      NOT NULL,
    real_ticker       VARCHAR      NOT NULL,
    display_name      VARCHAR,
    native_currency   VARCHAR      NOT NULL DEFAULT 'USD',
    exchange          VARCHAR,
    isin              VARCHAR,
    asset_class_id    INTEGER,
    source            VARCHAR      NOT NULL,
    confidence        FLOAT        NOT NULL DEFAULT 1.0,
    last_verified_at  TIMESTAMPTZ,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (instrument_id)
);
"""

_SEED = """
INSERT INTO instrument_registry
    (instrument_id, real_ticker, display_name, native_currency, exchange, isin, source, confidence)
VALUES
    (3040,  'SWDA.L',  'iShares Core MSCI World UCITS ETF',  'GBX', 'LSE',   'IE00B4L5Y983', 'manual', 1.0),
    (3434,  'CSPX.L',  'iShares Core S&P 500 UCITS ETF',     'GBX', 'LSE',   'IE00B5BMR087', 'manual', 1.0),
    (15435, 'EIMI.L',  'iShares Core MSCI EM IMI UCITS ETF', 'GBX', 'LSE',   'IE00BKM4GZ66', 'manual', 1.0),
    (3394,  'EUN5.DE', 'iShares EUR Corp Bond UCITS ETF',     'EUR', 'XETRA', 'IE00B3F81R35', 'manual', 1.0),
    (10569, 'IBCN.DE', 'iShares EUR Govt Bond 3-7yr UCITS',  'EUR', 'XETRA', 'IE00B3VTML14', 'manual', 1.0);
"""


@pytest.fixture()
def mem_client() -> DuckDBClient:
    """DuckDBClient in memoria con schema instrument_registry e seed."""
    raw = duckdb.connect(database=":memory:")
    raw.execute(_DDL)
    raw.execute(_SEED)

    client = object.__new__(DuckDBClient)
    client._conn = raw
    client._path = None  # type: ignore[assignment]
    client._read_only = False
    return client  # type: ignore[return-value]


@pytest.fixture()
def registry(mem_client: DuckDBClient) -> InstrumentRegistry:
    return InstrumentRegistry(client=mem_client)


# ─────────────────────────────────────────────────────────────── get / get_ticker

class TestGet:
    def test_get_known_id_returns_mapping(self, registry: InstrumentRegistry) -> None:
        """[DoD] InstrumentRegistry.get(3040) → SWDA.L."""
        m = registry.get(3040)
        assert m is not None
        assert isinstance(m, InstrumentMapping)
        assert m.real_ticker == "SWDA.L"
        assert m.native_currency == "GBX"
        assert m.isin == "IE00B4L5Y983"
        assert m.source == "manual"
        assert m.confidence == pytest.approx(1.0)

    def test_get_ticker_swda(self, registry: InstrumentRegistry) -> None:
        """BUG-005: #3040 deve essere SWDA.L, non EUNL.DE."""
        assert registry.get_ticker(3040) == "SWDA.L"

    def test_get_ticker_cspx(self, registry: InstrumentRegistry) -> None:
        assert registry.get_ticker(3434) == "CSPX.L"

    def test_get_ticker_eimi(self, registry: InstrumentRegistry) -> None:
        assert registry.get_ticker(15435) == "EIMI.L"

    def test_get_ticker_eun5(self, registry: InstrumentRegistry) -> None:
        assert registry.get_ticker(3394) == "EUN5.DE"

    def test_get_ticker_ibcn(self, registry: InstrumentRegistry) -> None:
        assert registry.get_ticker(10569) == "IBCN.DE"

    def test_get_unknown_id_returns_none(self, registry: InstrumentRegistry) -> None:
        assert registry.get(99999) is None

    def test_get_ticker_unknown_returns_none(self, registry: InstrumentRegistry) -> None:
        assert registry.get_ticker(99999) is None

    def test_all_ids_returns_five_seed_entries(self, registry: InstrumentRegistry) -> None:
        ids = registry.all_ids()
        assert set(ids) == {3040, 3434, 15435, 3394, 10569}

    def test_all_mappings_count(self, registry: InstrumentRegistry) -> None:
        mappings = registry.all_mappings()
        assert len(mappings) == 5

    def test_all_mappings_are_instrument_mapping(self, registry: InstrumentRegistry) -> None:
        for m in registry.all_mappings():
            assert isinstance(m, InstrumentMapping)


# ─────────────────────────────────────────────────────────────── register_from_api

class TestRegisterFromApi:
    def test_register_new_entry(self, registry: InstrumentRegistry) -> None:
        registry.register_from_api(
            instrument_id=9999,
            real_ticker="AAPL",
            native_currency="USD",
            confidence=0.8,
        )
        assert registry.get_ticker(9999) == "AAPL"

    def test_api_auto_does_not_overwrite_manual(self, registry: InstrumentRegistry) -> None:
        """[DoD] register_from_api non sovrascrive mapping manuali."""
        registry.register_from_api(
            instrument_id=3040,
            real_ticker="WRONG_TICKER",
            native_currency="USD",
            confidence=0.5,
        )
        # Il mapping manuale SWDA.L deve restare invariato
        assert registry.get_ticker(3040) == "SWDA.L"

    def test_api_auto_updates_existing_api_auto(self, registry: InstrumentRegistry) -> None:
        """Un mapping api_auto può essere sovrascritto da un altro api_auto."""
        registry.register_from_api(9998, "MSFT", confidence=0.7)
        registry.register_from_api(9998, "MSFT2", confidence=0.9)
        assert registry.get_ticker(9998) == "MSFT2"

    def test_register_confidence_stored(self, registry: InstrumentRegistry) -> None:
        registry.register_from_api(8888, "TSLA", confidence=0.75)
        m = registry.get(8888)
        assert m is not None
        assert m.source == "api_auto"
        assert m.confidence == pytest.approx(0.75)


# ─────────────────────────────────────────────────────────────── upsert_manual

class TestUpsertManual:
    def test_upsert_new_manual_entry(self, registry: InstrumentRegistry) -> None:
        registry.upsert_manual(
            instrument_id=7777,
            real_ticker="IVV",
            native_currency="USD",
            exchange="NYSE",
        )
        m = registry.get(7777)
        assert m is not None
        assert m.real_ticker == "IVV"
        assert m.source == "manual"
        assert m.confidence == pytest.approx(1.0)

    def test_upsert_manual_overwrites_api_auto(self, registry: InstrumentRegistry) -> None:
        """upsert_manual sovrascrive un mapping api_auto."""
        registry.register_from_api(6666, "OLD_TICKER", confidence=0.7)
        registry.upsert_manual(6666, "CORRECT_TICKER", native_currency="GBX")
        m = registry.get(6666)
        assert m is not None
        assert m.real_ticker == "CORRECT_TICKER"
        assert m.source == "manual"
