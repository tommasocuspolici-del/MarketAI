"""Test di non-regressione BUG-008.

BUG-008 (v7.3.0): _get_current_price_yf per ticker LSE (*.L) restituiva il
prezzo grezzo in GBX (pence sterling) invece di USD. Esempio: SWDA.L quotato
a 10 426 GBX veniva mostrato in P2 come 10 426 USD invece di ~132 USD.

Fix: la funzione pubblica get_live_price_usd() (in etoro_position_builder.py)
applica la conversione GBX→USD (/100 × GBP/USD) per tutti i ticker *.L.
"""
from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from personal.data_entry.etoro_position_builder import (
    _get_instrument_currency,
    _get_live_price_usd,
    _native_to_usd,
)

pytestmark = pytest.mark.regression


# ─── BUG-008: _get_live_price_usd per ticker LSE ─────────────────────────────

class TestBug008LivePriceUsd:
    def _mock_yf_returns_gbx(self, gbx_price: float):
        """Crea un mock yfinance che restituisce gbx_price come close."""
        mock_df = pd.DataFrame({"Close": [gbx_price]})
        return patch("yfinance.Ticker") , mock_df

    def test_swda_l_price_is_converted_to_usd(self):
        """BUG-008: SWDA.L quotato a 10426 GBX → USD (non GBX grezzo)."""
        mock_df = pd.DataFrame({"Close": [10426.0]})
        with patch("yfinance.Ticker") as mock_yf:
            mock_yf.return_value.history.return_value = mock_df
            price = _get_live_price_usd("SWDA.L", fx={"GBP_USD": 1.27, "EUR_USD": 1.08})

        assert price is not None, "BUG-008: prezzo non deve essere None"
        assert price < 500, \
            f"BUG-008: prezzo={price:.2f} sembra GBX grezzo (> 500 → /100 non applicato)"
        assert price > 50, \
            f"BUG-008: prezzo={price:.2f} è troppo basso per SWDA.L in USD"

    def test_swda_l_value_approximates_usd(self):
        """BUG-008: 10426 GBX / 100 * 1.27 ≈ 132.4 USD."""
        mock_df = pd.DataFrame({"Close": [10426.0]})
        with patch("yfinance.Ticker") as mock_yf:
            mock_yf.return_value.history.return_value = mock_df
            price = _get_live_price_usd("SWDA.L", fx={"GBP_USD": 1.27, "EUR_USD": 1.08})

        expected = 10426.0 / 100.0 * 1.27  # ≈ 132.41
        assert price == pytest.approx(expected, rel=1e-4), \
            f"BUG-008: atteso ~{expected:.2f} USD, ottenuto {price:.2f}"

    def test_gbx_price_not_returned_as_is(self):
        """BUG-008: il prezzo grezzo GBX (10426) non deve essere restituito invariato."""
        mock_df = pd.DataFrame({"Close": [10426.0]})
        with patch("yfinance.Ticker") as mock_yf:
            mock_yf.return_value.history.return_value = mock_df
            price = _get_live_price_usd("SWDA.L", fx={"GBP_USD": 1.27, "EUR_USD": 1.08})

        assert price != pytest.approx(10426.0, rel=0.01), \
            "BUG-008: prezzo GBX restituito invariato (conversione mancante)"


# ─── Helper: _get_instrument_currency ────────────────────────────────────────

class TestInstrumentCurrency:
    def test_lse_ticker_is_gbx(self):
        """BUG-008: ticker *.L deve avere valuta GBX."""
        assert _get_instrument_currency("SWDA.L") == "GBX"
        assert _get_instrument_currency("CSPX.L") == "GBX"
        assert _get_instrument_currency("EIMI.L") == "GBX"

    def test_xetra_ticker_is_eur(self):
        """BUG-007: ticker *.DE deve avere valuta EUR."""
        assert _get_instrument_currency("EUN5.DE") == "EUR"
        assert _get_instrument_currency("IBCN.DE") == "EUR"

    def test_usd_ticker_is_usd(self):
        assert _get_instrument_currency("AAPL")  == "USD"
        assert _get_instrument_currency("SPY")   == "USD"
        assert _get_instrument_currency("^GSPC") == "USD"


# ─── Helper: _native_to_usd ──────────────────────────────────────────────────

class TestNativeToUsd:
    def test_gbx_conversion(self):
        """BUG-006/008: GBX/100 * GBP/USD."""
        fx = {"GBP_USD": 1.27, "EUR_USD": 1.08}
        result = _native_to_usd(10000.0, "GBX", fx)
        assert result == pytest.approx(10000.0 / 100.0 * 1.27)

    def test_eur_conversion(self):
        fx = {"GBP_USD": 1.27, "EUR_USD": 1.08}
        result = _native_to_usd(118.88, "EUR", fx)
        assert result == pytest.approx(118.88 * 1.08, rel=1e-4)

    def test_usd_passthrough(self):
        result = _native_to_usd(150.0, "USD", {})
        assert result == pytest.approx(150.0)

    def test_gbx_result_is_always_less_than_input(self):
        """BUG-008: GBX → USD deve sempre produrre un valore < input (GBX >> USD)."""
        fx = {"GBP_USD": 1.30}
        raw_gbx = 9782.20
        usd = _native_to_usd(raw_gbx, "GBX", fx)
        assert usd < raw_gbx, \
            f"BUG-008: {usd:.2f} USD >= {raw_gbx:.2f} GBX — conversione /100 mancante"
