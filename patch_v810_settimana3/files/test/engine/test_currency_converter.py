"""Test unitari per engine/market_data/currency_converter.py.

Coverage target: ≥ 90% (DoD Settimana 3).

Test struttura:
  - TestGetInstrumentNativeCurrency: pure function, no I/O
  - TestCurrencyConverterToUsdUSD: fast path senza yfinance
  - TestCurrencyConverterToUsdFallback: conversioni con fallback mockato
  - TestCurrencyConverterFetchRate: cache, fallback yfinance down
  - TestTickerPriceToUsd: integration test get_instrument_native_currency + to_usd

Rif: ROADMAP_CODE_QUALITY_v1.0, Settimana 3 — Definition of Done.
"""
from __future__ import annotations

from unittest import mock

import pytest

from engine.market_data.currency_converter import (
    CurrencyConverter,
    get_instrument_native_currency,
)


# ═══════════════════════════════════════════════ get_instrument_native_currency


class TestGetInstrumentNativeCurrency:
    """get_instrument_native_currency è pura, O(suffissi), nessun I/O."""

    @pytest.mark.parametrize("ticker,expected", [
        ("SWDA.L",   "GBX"),   # London Stock Exchange
        ("CSPX.L",   "GBX"),
        ("EIMI.L",   "GBX"),
        ("EUN5.DE",  "EUR"),   # Xetra
        ("DAX.DE",   "EUR"),
        ("CAC40.PA", "EUR"),   # Euronext Paris
        ("SMI.SW",   "CHF"),   # SIX Swiss Exchange
        ("RY.TO",    "CAD"),   # Toronto
        ("CBA.AX",   "AUD"),   # ASX
        ("0700.HK",  "HKD"),   # Hong Kong
        ("9984.T",   "JPY"),   # Tokyo
        ("AAPL",     "USD"),   # no suffix → default
        ("^GSPC",    "USD"),   # indice → default
        ("EURUSD=X", "USD"),   # FX pair → default
        ("GC=F",     "USD"),   # futures → default
        ("BTC-USD",  "USD"),   # crypto → default
    ])
    def test_suffix_mapping(self, ticker: str, expected: str) -> None:
        """Ogni suffisso noto deve mappare alla valuta corretta."""
        assert get_instrument_native_currency(ticker) == expected

    def test_case_insensitive_ticker(self) -> None:
        """Il ticker in minuscolo deve funzionare come in maiuscolo."""
        assert get_instrument_native_currency("swda.l") == "GBX"
        assert get_instrument_native_currency("eun5.de") == "EUR"

    def test_unknown_suffix_defaults_to_usd(self) -> None:
        """Suffisso non noto → USD default."""
        assert get_instrument_native_currency("SOMETHING.XY") == "USD"

    def test_empty_string_defaults_to_usd(self) -> None:
        """Stringa vuota → USD default (no crash)."""
        assert get_instrument_native_currency("") == "USD"


# ═══════════════════════════════════════════════ CurrencyConverter.to_usd


class TestCurrencyConverterToUsdUSD:
    """USD → USD: fast path senza nessun I/O o fetch."""

    def test_usd_is_identity(self) -> None:
        conv = CurrencyConverter()
        assert conv.to_usd(123.45, "USD") == pytest.approx(123.45)

    def test_usd_zero(self) -> None:
        conv = CurrencyConverter()
        assert conv.to_usd(0.0, "USD") == pytest.approx(0.0)

    def test_usd_no_yfinance_call(self) -> None:
        """Per USD non deve essere fatto nessun fetch yfinance."""
        conv = CurrencyConverter()
        with mock.patch.object(conv, "_fetch_rate") as mock_fetch:
            conv.to_usd(100.0, "USD")
        mock_fetch.assert_not_called()


class TestCurrencyConverterToUsdWithFallback:
    """Conversioni con tasso mockato (evita dipendenza da yfinance in CI)."""

    def _make_converter_with_rates(self, rates: dict[str, float]) -> CurrencyConverter:
        """Helper: crea CurrencyConverter con cache pre-popolata."""
        conv = CurrencyConverter()
        conv._rate_cache.update(rates)
        return conv

    # ── GBX ──────────────────────────────────────────────────────────────────

    def test_gbx_to_usd_conversion(self) -> None:
        """[DoD] GBX 10426 con GBP/USD=1.27 → ~132.21 USD.

        Formula: price / 100 * gbp_usd = 10426 / 100 * 1.27 = 132.21
        """
        conv = self._make_converter_with_rates({"GBP": 1.27})
        result = conv.to_usd(10_426.0, "GBX")
        # Range del DoD: [125, 145] con GBP/USD ~ 1.27
        assert 125.0 < result < 145.0
        assert result == pytest.approx(10_426.0 / 100.0 * 1.27, rel=1e-6)

    def test_gbx_uses_gbp_rate_divided_by_100(self) -> None:
        """Verifica esplicitamente la formula GBX = GBP/100."""
        conv = self._make_converter_with_rates({"GBP": 1.30})
        expected = 500.0 / 100.0 * 1.30  # = 6.50
        assert conv.to_usd(500.0, "GBX") == pytest.approx(expected)

    # ── EUR ──────────────────────────────────────────────────────────────────

    def test_eur_to_usd_conversion(self) -> None:
        """[DoD] EUR 118.88 con EUR/USD=1.08 → ~128.39 USD.

        Range del DoD: [120, 140].
        """
        conv = self._make_converter_with_rates({"EUR": 1.08})
        result = conv.to_usd(118.88, "EUR")
        assert 120.0 < result < 140.0
        assert result == pytest.approx(118.88 * 1.08, rel=1e-6)

    def test_eur_uses_direct_multiplication(self) -> None:
        """EUR → USD: prezzo × EUR/USD (nessuna divisione per 100)."""
        conv = self._make_converter_with_rates({"EUR": 1.10})
        assert conv.to_usd(100.0, "EUR") == pytest.approx(110.0)

    # ── Altre valute ──────────────────────────────────────────────────────────

    def test_chf_to_usd(self) -> None:
        conv = self._make_converter_with_rates({"CHF": 1.12})
        assert conv.to_usd(100.0, "CHF") == pytest.approx(112.0)

    def test_jpy_to_usd(self) -> None:
        """JPY con tasso bassissimo."""
        conv = self._make_converter_with_rates({"JPY": 0.0065})
        assert conv.to_usd(10_000.0, "JPY") == pytest.approx(65.0)

    def test_hkd_to_usd(self) -> None:
        conv = self._make_converter_with_rates({"HKD": 0.128})
        assert conv.to_usd(1_000.0, "HKD") == pytest.approx(128.0)


# ═══════════════════════════════════════════════ _fetch_rate e cache


class TestCurrencyConverterFetchRate:
    """Test del meccanismo di fetch e caching dei tassi FX."""

    def test_rate_cached_after_first_call(self) -> None:
        """Il tasso viene cachato dopo il primo fetch: la seconda chiamata non fa I/O."""
        conv = CurrencyConverter()
        # Mocka yfinance per dare un tasso controllato
        with mock.patch("engine.market_data.currency_converter.log"):
            conv._rate_cache["EUR"] = 1.09  # pre-popola la cache

        # La seconda chiamata deve leggere dalla cache (no mock yfinance)
        rate = conv._fetch_rate("EUR")
        assert rate == pytest.approx(1.09)

    def test_fallback_used_when_yfinance_unavailable(self) -> None:
        """Quando yfinance lancia eccezione, si usa il fallback da OP_CONFIG."""
        conv = CurrencyConverter()

        # yfinance solleva ImportError (non installato in questo test)
        with mock.patch(
            "engine.market_data.currency_converter.log"
        ), mock.patch.dict(
            "sys.modules", {"yfinance": None}
        ):
            rate = conv._fetch_rate("GBP")

        # Deve usare OP_CONFIG.fx_fallbacks.gbp_usd (1.27)
        assert rate == pytest.approx(CurrencyConverter._FALLBACKS["GBP"])

    def test_unknown_currency_returns_fallback_1(self) -> None:
        """Valuta non in _YF_PAIRS → fallback di default (1.0 se non in _FALLBACKS)."""
        conv = CurrencyConverter()
        rate = conv._fetch_rate("XYZ")  # valuta sconosciuta
        assert rate == pytest.approx(1.0)

    def test_fallback_gbp_matches_op_config(self) -> None:
        """Il fallback GBP deve corrispondere a OP_CONFIG.fx_fallbacks.gbp_usd."""
        from shared.config.operational_config import OP_CONFIG
        assert CurrencyConverter._FALLBACKS["GBP"] == pytest.approx(OP_CONFIG.fx_fallbacks.gbp_usd)

    def test_fallback_eur_matches_op_config(self) -> None:
        """Il fallback EUR deve corrispondere a OP_CONFIG.fx_fallbacks.eur_usd."""
        from shared.config.operational_config import OP_CONFIG
        assert CurrencyConverter._FALLBACKS["EUR"] == pytest.approx(OP_CONFIG.fx_fallbacks.eur_usd)


# ═══════════════════════════════════════════════ ticker_price_to_usd


class TestTickerPriceToUsd:
    """ticker_price_to_usd = get_instrument_native_currency + to_usd."""

    def test_swda_l_same_as_gbx(self) -> None:
        """[DoD] ticker_price_to_usd(10426, 'SWDA.L') == to_usd(10426, 'GBX')."""
        conv = CurrencyConverter()
        conv._rate_cache["GBP"] = 1.27

        via_ticker = conv.ticker_price_to_usd(10_426.0, "SWDA.L")
        via_ccy = conv.to_usd(10_426.0, "GBX")
        assert via_ticker == pytest.approx(via_ccy)

    def test_eun5_de_same_as_eur(self) -> None:
        """ticker_price_to_usd(118.88, 'EUN5.DE') == to_usd(118.88, 'EUR')."""
        conv = CurrencyConverter()
        conv._rate_cache["EUR"] = 1.08

        via_ticker = conv.ticker_price_to_usd(118.88, "EUN5.DE")
        via_ccy = conv.to_usd(118.88, "EUR")
        assert via_ticker == pytest.approx(via_ccy)

    def test_aapl_usd_unchanged(self) -> None:
        """Ticker USA: prezzo invariato, nessun I/O."""
        conv = CurrencyConverter()
        with mock.patch.object(conv, "_fetch_rate") as mock_fetch:
            result = conv.ticker_price_to_usd(185.50, "AAPL")
        assert result == pytest.approx(185.50)
        mock_fetch.assert_not_called()

    def test_index_ticker_usd_unchanged(self) -> None:
        """Ticker indice (^GSPC): USD default, nessuna conversione."""
        conv = CurrencyConverter()
        with mock.patch.object(conv, "_fetch_rate") as mock_fetch:
            result = conv.ticker_price_to_usd(5_400.0, "^GSPC")
        assert result == pytest.approx(5_400.0)
        mock_fetch.assert_not_called()

    def test_gbx_price_in_realistic_usd_range(self) -> None:
        """SWDA.L a ~10426 GBX deve valere ~100-200 USD (non ~10000)."""
        conv = CurrencyConverter()
        conv._rate_cache["GBP"] = 1.27
        result = conv.ticker_price_to_usd(10_426.0, "SWDA.L")
        # Verifica anti-regressione: il bug era restituire ~10426 invece di ~132
        assert result < 300.0, f"Prezzo troppo alto ({result}): GBX non convertito correttamente"
        assert result > 50.0, f"Prezzo troppo basso ({result}): conversione errata"
