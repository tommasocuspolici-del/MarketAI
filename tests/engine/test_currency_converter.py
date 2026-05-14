"""Test unitari per engine/market_data/currency_converter.py.

Coverage target: ≥ 90%.
Rif: ROADMAP_CODE_QUALITY_v1.0, Settimana 3 (DoD).
"""
from __future__ import annotations
from unittest import mock
import pytest
from engine.market_data.currency_converter import (
    CurrencyConverter, get_instrument_native_currency,
)


class TestGetInstrumentNativeCurrency:
    @pytest.mark.parametrize("ticker,expected", [
        ("SWDA.L", "GBX"), ("CSPX.L", "GBX"),
        ("EUN5.DE", "EUR"), ("DAX.DE", "EUR"),
        ("SMI.SW", "CHF"), ("9984.T", "JPY"),
        ("AAPL", "USD"), ("^GSPC", "USD"), ("GC=F", "USD"),
    ])
    def test_mapping(self, ticker: str, expected: str) -> None:
        assert get_instrument_native_currency(ticker) == expected

    def test_case_insensitive(self) -> None:
        assert get_instrument_native_currency("swda.l") == "GBX"

    def test_unknown_suffix_usd(self) -> None:
        assert get_instrument_native_currency("FAKE.XY") == "USD"

    def test_empty_string_usd(self) -> None:
        assert get_instrument_native_currency("") == "USD"


class TestCurrencyConverterToUsd:
    def _conv(self, rates: dict) -> CurrencyConverter:
        c = CurrencyConverter()
        c._rate_cache.update(rates)
        return c

    def test_usd_identity(self) -> None:
        c = CurrencyConverter()
        assert c.to_usd(100.0, "USD") == pytest.approx(100.0)

    def test_usd_no_fetch(self) -> None:
        c = CurrencyConverter()
        with mock.patch.object(c, "_fetch_rate") as m:
            c.to_usd(100.0, "USD")
        m.assert_not_called()

    def test_gbx_conversion_range(self) -> None:
        """[DoD] 10426 GBX con GBP/USD=1.27 → 125-145 USD."""
        c = self._conv({"GBP": 1.27})
        r = c.to_usd(10_426.0, "GBX")
        assert 125.0 < r < 145.0
        assert r == pytest.approx(10_426.0 / 100.0 * 1.27, rel=1e-6)

    def test_gbx_not_10k(self) -> None:
        """Anti-regressione: GBX non deve dare ~10000 USD."""
        c = self._conv({"GBP": 1.27})
        assert c.to_usd(10_426.0, "GBX") < 500.0

    def test_eur_conversion_range(self) -> None:
        """[DoD] 118.88 EUR con EUR/USD=1.08 → 120-140 USD."""
        c = self._conv({"EUR": 1.08})
        r = c.to_usd(118.88, "EUR")
        assert 120.0 < r < 140.0

    def test_chf_conversion(self) -> None:
        c = self._conv({"CHF": 1.12})
        assert c.to_usd(100.0, "CHF") == pytest.approx(112.0)

    def test_fallback_matches_op_config(self) -> None:
        from shared.config.operational_config import OP_CONFIG
        assert CurrencyConverter._FALLBACKS["GBP"] == pytest.approx(OP_CONFIG.fx_fallbacks.gbp_usd)
        assert CurrencyConverter._FALLBACKS["EUR"] == pytest.approx(OP_CONFIG.fx_fallbacks.eur_usd)

    def test_rate_cached_after_first_call(self) -> None:
        c = CurrencyConverter()
        c._rate_cache["EUR"] = 1.09
        r = c._fetch_rate("EUR")
        assert r == pytest.approx(1.09)

    def test_ticker_price_swda_l(self) -> None:
        """[DoD] ticker_price_to_usd("SWDA.L", 10426) == to_usd(10426, "GBX")."""
        c = self._conv({"GBP": 1.27})
        assert c.ticker_price_to_usd(10_426.0, "SWDA.L") == pytest.approx(
            c.to_usd(10_426.0, "GBX")
        )

    def test_ticker_aapl_no_fetch(self) -> None:
        c = CurrencyConverter()
        with mock.patch.object(c, "_fetch_rate") as m:
            r = c.ticker_price_to_usd(185.5, "AAPL")
        assert r == pytest.approx(185.5)
        m.assert_not_called()
