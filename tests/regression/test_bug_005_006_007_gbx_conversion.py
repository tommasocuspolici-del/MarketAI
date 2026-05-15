"""Test di non-regressione BUG-005, BUG-006, BUG-007.

BUG-005 (v7.4.0): instrument_id #3040 era mappato a "EUNL.DE" (iShares MSCI World
  su Xetra, EUR) invece di "SWDA.L" (iShares Core MSCI World su LSE, GBX).
  Conseguenza: prezzi in EUR usati invece di GBX, P/L completamente errato.

BUG-006 (v7.4.0): openRate dall'API eToro per ETF LSE (*.L) è in GBX (pence
  sterling), NON in USD. Il codice precedente lo trattava come USD diretto,
  gonfiando il costo base di ~100x (es. 9782.20 GBX → 9782.20 USD invece di ~124.3 USD).

BUG-007 (v7.4.0): currency hardcoded "USD" per posizioni EUR/GBX prima della
  conversione. open_price rimaneva nella valuta nativa invece di essere convertito.
  Risultato: P/L di -98% per posizioni LSE.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from engine.market_data.currency_converter import CurrencyConverter
from personal.data_entry.etoro_position_builder import _api_positions_to_dataframe

pytestmark = pytest.mark.regression

# ─── Fixture helpers ─────────────────────────────────────────────────────────

def _make_position(
    instrument_id: int = 3040,
    open_rate: float = 9782.20,  # GBX
    close_rate: float = 10426.0,  # GBX
    units: float = 5.0,
    pnl: float = 32.2,
    amount: float = 491.0,
    ticker_from_api: str | None = None,
    direction: str = "BUY",
    order_id: int | None = None,
    display_name_from_api: str | None = "iShares Core MSCI World",
    open_date_time: str | None = "2024-01-15T10:30:00Z",
) -> MagicMock:
    pos = MagicMock()
    pos.instrument_id = instrument_id
    pos.open_rate = open_rate
    pos.close_rate = close_rate
    pos.units = units
    pos.pnl = pnl
    pos.amount = amount
    pos.ticker_from_api = ticker_from_api
    pos.direction = direction
    pos.order_id = order_id
    pos.display_name_from_api = display_name_from_api
    pos.open_date_time = open_date_time
    return pos


def _make_instrument(instrument_id: int, best_symbol: str, name: str) -> MagicMock:
    inst = MagicMock()
    inst.instrument_id = instrument_id
    inst.best_symbol = best_symbol
    inst.name = name
    return inst


def _make_rate(
    instrument_id: int,
    conversion_rate_bid: float | None = None,
    conversion_rate_ask: float | None = None,
    mid_price: float | None = None,
) -> MagicMock:
    rate = MagicMock()
    rate.conversion_rate_bid = conversion_rate_bid
    rate.conversion_rate_ask = conversion_rate_ask
    rate.mid_price = mid_price
    return rate


# ─── BUG-005: SWDA.L mapping ─────────────────────────────────────────────────

class TestBug005InstrumentMapping:
    def test_instrument_id_3040_maps_to_swda_l_in_seed(self):
        """BUG-005: #3040 deve essere SWDA.L, non EUNL.DE — seed fallback."""
        from engine.market_data.instrument_registry import _SEED_FALLBACK
        assert _SEED_FALLBACK[3040].real_ticker == "SWDA.L", \
            "BUG-005: seed #3040 deve essere SWDA.L"

    def test_instrument_id_3040_maps_to_swda_l_in_registry(self):
        """BUG-005: InstrumentRegistry.get_ticker(3040) == 'SWDA.L' da DB in memoria."""
        import duckdb
        from shared.db.duckdb_client import DuckDBClient
        from engine.market_data.instrument_registry import InstrumentRegistry

        raw = duckdb.connect(database=":memory:")
        raw.execute("""
            CREATE TABLE instrument_registry (
                instrument_id INTEGER NOT NULL PRIMARY KEY,
                real_ticker VARCHAR NOT NULL, display_name VARCHAR,
                native_currency VARCHAR NOT NULL DEFAULT 'USD',
                exchange VARCHAR, isin VARCHAR, source VARCHAR NOT NULL,
                confidence FLOAT NOT NULL DEFAULT 1.0,
                last_verified_at TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        raw.execute(
            "INSERT INTO instrument_registry (instrument_id, real_ticker, native_currency, source, confidence)"
            " VALUES (3040, 'SWDA.L', 'GBX', 'manual', 1.0)"
        )
        client = object.__new__(DuckDBClient)
        client._conn = raw
        client._path = None  # type: ignore[assignment]
        client._read_only = False

        registry = InstrumentRegistry(client=client)  # type: ignore[arg-type]
        assert registry.get_ticker(3040) == "SWDA.L", "BUG-005: #3040 deve essere SWDA.L"

    def test_instrument_id_3040_not_eunl_de(self):
        """BUG-005: #3040 NON deve essere EUNL.DE (il vecchio valore errato)."""
        from engine.market_data.instrument_registry import _SEED_FALLBACK
        assert _SEED_FALLBACK[3040].real_ticker != "EUNL.DE", \
            "BUG-005: regressione! #3040 è tornato a EUNL.DE"


# ─── BUG-006: GBX → USD conversion ──────────────────────────────────────────

class TestBug006GbxConversion:
    def test_openrate_gbx_9782_converts_to_usd_range(self):
        """BUG-006: openRate 9782.20 GBX → USD (non trattato come USD diretto)."""
        conv = CurrencyConverter()
        with patch.object(conv, "_fetch_rate", return_value=1.27):
            result = conv.to_usd(9782.20, "GBX")

        # 9782.20 GBX / 100 * 1.27 = 124.23 USD
        assert 100 < result < 200, \
            f"BUG-006: {result:.2f} non è nell'intervallo USD realistico (100-200)"
        assert result < 500, \
            f"BUG-006: {result:.2f} sembra ancora in GBX (> 500 implica divisione per 100 mancante)"
        assert result == pytest.approx(9782.20 / 100 * 1.27, rel=1e-4)

    def test_openrate_gbx_not_treated_as_usd(self):
        """BUG-006: 9782.20 non deve rimanere ~9782 USD (×100 errore)."""
        conv = CurrencyConverter()
        with patch.object(conv, "_fetch_rate", return_value=1.27):
            result = conv.to_usd(9782.20, "GBX")
        assert result < 1000, \
            f"BUG-006: {result:.2f} indica che GBX NON è stato diviso per 100"

    def test_gbx_conversion_uses_gbp_rate(self):
        """BUG-006: la conversione GBX usa GBP/USD (non un tasso diretto GBX/USD)."""
        conv = CurrencyConverter()
        gbp_rate = 1.30
        with patch.object(conv, "_fetch_rate", return_value=gbp_rate):
            result = conv.to_usd(10000.0, "GBX")
        expected = 10000.0 / 100.0 * gbp_rate  # = 130.0
        assert result == pytest.approx(expected, rel=1e-4)

    def test_usd_passthrough_unchanged(self):
        """BUG-006: prezzi USD non devono essere modificati."""
        conv = CurrencyConverter()
        result = conv.to_usd(150.0, "USD")
        assert result == pytest.approx(150.0)


# ─── BUG-007: API positions DataFrame currency ───────────────────────────────

class TestBug007ApiPositionsCurrency:
    def _build_swda_df(self, open_rate: float = 9782.20) -> pd.DataFrame:
        """Costruisce DataFrame da una posizione SWDA.L con conversion rate esplicito."""
        pos = _make_position(instrument_id=3040, open_rate=open_rate, close_rate=10426.0)
        inst = _make_instrument(3040, "SWDA.L", "iShares Core MSCI World")
        # Simula conversionRateAsk/Bid dall'API eToro (GBX→USD ~ 0.01273)
        gbx_to_usd = 1.27 / 100  # ≈ 0.01270
        rate = _make_rate(
            3040,
            conversion_rate_bid=gbx_to_usd * 0.999,
            conversion_rate_ask=gbx_to_usd * 1.001,
            mid_price=10426.0,
        )
        return _api_positions_to_dataframe(
            positions=[pos],
            instruments={3040: inst},
            rates={3040: rate},
            fx={"GBP_USD": 1.27, "EUR_USD": 1.08},
        )

    def test_open_price_is_in_usd_range(self):
        """BUG-007: open_price deve essere in USD (~124 USD), non GBX (~9782)."""
        df = self._build_swda_df(open_rate=9782.20)
        open_price = float(df.iloc[0]["open_price"])
        assert open_price < 500, \
            f"BUG-007: open_price={open_price:.2f} sembra ancora in GBX (> 500)"
        assert open_price > 50, \
            f"BUG-007: open_price={open_price:.2f} è troppo basso per essere USD"

    def test_currency_field_is_usd_after_conversion(self):
        """BUG-007: currency deve essere 'USD' dopo la conversione."""
        df = self._build_swda_df()
        assert df.iloc[0]["currency"] == "USD", \
            "BUG-007: currency deve essere 'USD' dopo la normalizzazione"

    def test_open_price_not_gbx_raw_value(self):
        """BUG-007: open_price 9782.20 non deve comparire nel DataFrame post-conversione."""
        df = self._build_swda_df(open_rate=9782.20)
        open_price = float(df.iloc[0]["open_price"])
        assert open_price != pytest.approx(9782.20, rel=0.01), \
            "BUG-007: open_price è il valore grezzo GBX, conversione non applicata"
