"""Test progettati per killare mutanti comuni in moduli critici.

Questi test complementano il mutation testing (mutmut) per i moduli che
gestiscono calcoli finanziari. Su Windows mutmut richiede WSL (issue #397).

Obiettivo mutation score:
  - currency_converter.py: ≥ 70%
  - etoro_aggregator.py:   ≥ 65%

Strategia: ogni test verifica una specifica operazione matematica o
condizione limite in modo da fallire se un mutante cambia:
  - operatori aritmetici: + ↔ -, * ↔ /, /100 ↔ *100
  - confronti: < ↔ >, == ↔ !=, >= ↔ <=
  - valori di ritorno: None ↔ valore, fallback mancante
"""
from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from engine.market_data.currency_converter import (
    CurrencyConverter,
    get_instrument_native_currency,
)
from personal.data_entry.etoro_aggregator import (
    _aggregate_positions,
    aggregate_by_real_ticker,
    update_live_prices,
)


# ──────────────────────────────────────────────────────── CurrencyConverter

class TestCurrencyConverterMathInvariants:
    """Verifica le invarianti matematiche di to_usd().

    Ogni test è progettato per rilevare uno specifico mutante comune.
    """

    def _conv_with_rate(self, rate: float) -> CurrencyConverter:
        conv = CurrencyConverter()
        conv._rate_cache["GBP"] = rate
        conv._rate_cache["EUR"] = rate
        return conv

    # ── GBX divide-by-100 mutant ──────────────────────────────────────────

    def test_gbx_divides_by_100(self):
        """Mutante: /100 → *100. Verifica: 100 GBX != 100 USD."""
        conv = self._conv_with_rate(1.0)
        result = conv.to_usd(100.0, "GBX")
        # Se /100 fosse *100, result sarebbe 10000 invece di 1.0
        assert result == pytest.approx(1.0), f"GBX /100 fallito: {result}"
        assert result < 100.0, "Mutante /100 → *100 non rilevato"

    def test_gbx_multiplied_by_rate(self):
        """Mutante: *rate → /rate. Verifica: risultato proporzionale al rate."""
        conv_127 = self._conv_with_rate(1.27)
        conv_100 = self._conv_with_rate(1.00)
        r1 = conv_127.to_usd(10000.0, "GBX")
        r0 = conv_100.to_usd(10000.0, "GBX")
        # r1 = 10000/100*1.27 = 127, r0 = 10000/100*1.00 = 100
        assert r1 > r0, "Mutante *rate → /rate non rilevato"
        assert r1 == pytest.approx(127.0, rel=1e-4)

    def test_gbx_formula_is_price_div_100_times_rate(self):
        """Verifica la formula esatta: prezzo / 100 * tasso."""
        price, rate = 9782.20, 1.27
        conv = self._conv_with_rate(rate)
        expected = price / 100.0 * rate  # = 124.2339
        result = conv.to_usd(price, "GBX")
        assert result == pytest.approx(expected, rel=1e-5)

    # ── EUR multiply mutant ───────────────────────────────────────────────

    def test_eur_multiplied_not_divided_by_rate(self):
        """Mutante: *rate → /rate per EUR. 118.88 EUR con rate=1.08 → 128.39 USD."""
        conv = self._conv_with_rate(1.08)
        result = conv.to_usd(118.88, "EUR")
        # Se /rate: 118.88/1.08 = 110.07; se *rate: 118.88*1.08 = 128.39
        assert result == pytest.approx(118.88 * 1.08, rel=1e-4)
        assert result > 118.88, "Mutante *rate → /rate non rilevato per EUR"

    def test_eur_result_increases_with_higher_rate(self):
        """Mutante: se moltiplicazione diventasse divisione, rate più alto → risultato minore."""
        conv_low  = self._conv_with_rate(1.05)
        conv_high = self._conv_with_rate(1.15)
        r_low  = conv_low.to_usd(100.0, "EUR")
        r_high = conv_high.to_usd(100.0, "EUR")
        assert r_high > r_low, "EUR: rate più alto deve produrre USD più alti"

    # ── USD passthrough mutant ────────────────────────────────────────────

    def test_usd_returns_exact_value(self):
        """Mutante: return float(price) → return 0.0 o altro."""
        conv = CurrencyConverter()
        for price in [1.0, 100.0, 5250.43, 0.0001]:
            assert conv.to_usd(price, "USD") == pytest.approx(price)

    def test_usd_not_affected_by_rate_cache(self):
        """Mutante: USD passa per il rate lookup invece del early return."""
        conv = CurrencyConverter()
        conv._rate_cache["GBP"] = 999.0  # rate assurdo che non deve influire su USD
        result = conv.to_usd(150.0, "USD")
        assert result == pytest.approx(150.0)

    # ── ticker_price_to_usd delegates correctly ───────────────────────────

    def test_ticker_price_to_usd_lse_uses_gbx(self):
        """Mutante: se la delega non usa GBX, il risultato è USD diretto (>>×100)."""
        conv = self._conv_with_rate(1.27)
        result = conv.ticker_price_to_usd(10000.0, "SWDA.L")
        expected = 10000.0 / 100.0 * 1.27
        assert result == pytest.approx(expected, rel=1e-4)

    def test_ticker_price_to_usd_usd_is_passthrough(self):
        """Mutante: ticker USD viene processato come altra valuta."""
        conv = CurrencyConverter()
        assert conv.ticker_price_to_usd(5250.0, "^GSPC") == pytest.approx(5250.0)

    # ── fallback boundary ─────────────────────────────────────────────────

    def test_fallback_used_when_yfinance_fails(self):
        """Mutante: fallback non usato → eccezione propagata invece di valore."""
        conv = CurrencyConverter()
        with patch("yfinance.Ticker", side_effect=RuntimeError("network down")):
            result = conv.to_usd(10000.0, "GBX")
        assert result is not None
        assert isinstance(result, float)
        assert result > 0


class TestGetInstrumentNativeCurrency:
    """Verifica _SUFFIX_TO_CURRENCY per mutanti sul matching."""

    def test_case_insensitive(self):
        """Mutante: .upper() rimosso → case mismatch = USD."""
        assert get_instrument_native_currency("swda.l") == "GBX"
        assert get_instrument_native_currency("EUN5.de") == "EUR"

    def test_suffix_order_irrelevant_for_unique_match(self):
        """Verifica che tutti i suffissi noti restituiscano la valuta corretta."""
        expected = {
            "SWDA.L": "GBX",
            "EUN5.DE": "EUR",
            "CSGN.SW": "CHF",
            "RY.TO": "CAD",
            "BHP.AX": "AUD",
            "9988.HK": "HKD",
            "9984.T": "JPY",
        }
        for ticker, ccy in expected.items():
            assert get_instrument_native_currency(ticker) == ccy, \
                f"Valuta errata per {ticker}: attesa {ccy}"

    def test_unknown_suffix_returns_usd(self):
        """Mutante: default return "" invece di "USD"."""
        assert get_instrument_native_currency("AAPL") == "USD"
        assert get_instrument_native_currency("MSFT") == "USD"
        assert get_instrument_native_currency("BTC-USD") == "USD"


# ──────────────────────────────────────────────────────── EtoroAggregator

class TestAggregatePositionsMathInvariants:
    """Verifica le invarianti matematiche di _aggregate_positions()."""

    def _make_df(self, rows: list[dict]) -> pd.DataFrame:
        return pd.DataFrame(rows)

    def test_total_units_is_sum(self):
        """Mutante: sum → first. Verifica che le quantità siano sommante."""
        df = self._make_df([
            {"real_ticker": "AAPL", "quantity": 3.0, "open_price": 150.0, "current_price": 180.0, "raw_action": "Apple"},
            {"real_ticker": "AAPL", "quantity": 2.0, "open_price": 155.0, "current_price": 180.0, "raw_action": "Apple"},
        ])
        result = _aggregate_positions(df)
        assert float(result.iloc[0]["total_units"]) == pytest.approx(5.0), \
            "total_units deve essere la somma delle quantità"

    def test_avg_open_price_is_weighted_average(self):
        """Mutante: weighted avg → unweighted avg. Verifica calcolo corretto."""
        df = self._make_df([
            {"real_ticker": "AAPL", "quantity": 3.0, "open_price": 100.0, "current_price": 120.0, "raw_action": "A"},
            {"real_ticker": "AAPL", "quantity": 1.0, "open_price": 140.0, "current_price": 120.0, "raw_action": "A"},
        ])
        result = _aggregate_positions(df)
        # Investito totale: 3*100 + 1*140 = 440; unità: 4; avg = 440/4 = 110
        expected_avg = (3.0 * 100.0 + 1.0 * 140.0) / 4.0
        assert float(result.iloc[0]["avg_open_price"]) == pytest.approx(expected_avg), \
            "avg_open_price deve essere la media ponderata per quantità"

    def test_market_value_is_units_times_price(self):
        """Mutante: * → +. Verifica moltiplicazione quantità × prezzo corrente."""
        df = self._make_df([
            {"real_ticker": "MSFT", "quantity": 4.0, "open_price": 200.0, "current_price": 250.0, "raw_action": "M"},
        ])
        result = _aggregate_positions(df)
        expected_mv = 4.0 * 250.0
        assert float(result.iloc[0]["market_value"]) == pytest.approx(expected_mv)

    def test_profit_eur_is_market_minus_invested(self):
        """Mutante: market - invested → invested - market (segno invertito)."""
        df = self._make_df([
            {"real_ticker": "TSLA", "quantity": 2.0, "open_price": 200.0, "current_price": 300.0, "raw_action": "T"},
        ])
        result = _aggregate_positions(df)
        invested = 2.0 * 200.0   # 400
        market   = 2.0 * 300.0   # 600
        expected_profit = market - invested  # +200
        assert float(result.iloc[0]["profit_eur"]) == pytest.approx(expected_profit), \
            "profit_eur deve essere positivo quando prezzo corrente > open price"

    def test_profit_negative_when_loss(self):
        """Mutante: segno profit. Verifica che le perdite siano negative."""
        df = self._make_df([
            {"real_ticker": "COIN", "quantity": 10.0, "open_price": 300.0, "current_price": 200.0, "raw_action": "C"},
        ])
        result = _aggregate_positions(df)
        assert float(result.iloc[0]["profit_eur"]) < 0, \
            "profit_eur deve essere negativo quando current_price < open_price"

    def test_multiple_tickers_grouped_independently(self):
        """Mutante: groupby si fonde. Verifica separazione per ticker."""
        df = self._make_df([
            {"real_ticker": "AAPL", "quantity": 2.0, "open_price": 150.0, "current_price": 180.0, "raw_action": "A"},
            {"real_ticker": "MSFT", "quantity": 3.0, "open_price": 200.0, "current_price": 250.0, "raw_action": "M"},
        ])
        result = _aggregate_positions(df).set_index("ticker")
        assert float(result.loc["AAPL"]["total_units"]) == pytest.approx(2.0)
        assert float(result.loc["MSFT"]["total_units"]) == pytest.approx(3.0)
        assert float(result.loc["AAPL"]["total_units"]) != float(result.loc["MSFT"]["total_units"])
