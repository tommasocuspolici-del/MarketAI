"""Tests for shared.fx_service."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from shared.exceptions import DataError
from shared.fx_service import FxService, _STUB_EUR_RATES
from shared.types import Currency, Money

# Stub rates injected by the autouse fixture — no network calls in unit tests.
_STUB_LIVE: dict[Currency, Decimal] = dict(_STUB_EUR_RATES)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch live fetcher so unit tests never hit yfinance."""
    monkeypatch.setattr("shared.fx_service._fetch_live_eur_rates", lambda: _STUB_LIVE)


class TestFxService:
    def test_get_rate_same_currency_is_one(self) -> None:
        svc = FxService()
        rate = svc.get_rate(Currency.EUR, Currency.EUR)
        assert rate.rate == Decimal("1.0")

    def test_get_rate_eur_to_usd_positive(self) -> None:
        svc = FxService()
        rate = svc.get_rate(Currency.EUR, Currency.USD)
        assert rate.rate > Decimal("0")
        assert rate.base == Currency.EUR
        assert rate.quote == Currency.USD

    def test_triangulation_via_eur(self) -> None:
        svc = FxService()
        rate = svc.get_rate(Currency.USD, Currency.GBP)
        assert rate.source in ("live", "stub")
        # Deve essere coerente: USD→EUR→GBP ≈ diretta
        usd_to_eur = svc.get_rate(Currency.USD, Currency.EUR).rate
        eur_to_gbp = svc.get_rate(Currency.EUR, Currency.GBP).rate
        assert rate.rate == pytest.approx(usd_to_eur * eur_to_gbp, rel=1e-9)

    def test_convert_money_same_currency(self) -> None:
        svc = FxService()
        m = Money(Decimal("100"), Currency.EUR)
        assert svc.convert(m, Currency.EUR) == m

    def test_convert_money_different_currency(self) -> None:
        svc = FxService()
        m = Money(Decimal("100"), Currency.EUR)
        result = svc.convert(m, Currency.USD)
        assert result.currency == Currency.USD
        assert result.amount > Decimal("0")

    def test_unknown_currency_raises(self) -> None:
        svc = FxService()
        with pytest.raises(DataError):
            svc.get_rate(Currency.EUR, Currency.BTC)

    def test_set_rate_overrides(self) -> None:
        svc = FxService()
        custom = Decimal("2.0")
        svc.set_rate(Currency.EUR, Currency.USD, custom)
        rate = svc.get_rate(Currency.EUR, Currency.USD)
        assert rate.rate == custom

    def test_source_mode_after_live_fetch(self) -> None:
        """Quando il fetcher restituisce dati, source_mode è 'live'."""
        svc = FxService()
        assert svc.source_mode == "live"

    def test_source_mode_stub_on_fetch_failure(self) -> None:
        """Quando il fetcher restituisce None, source_mode è 'stub'."""
        with patch("shared.fx_service._fetch_live_eur_rates", return_value=None):
            svc = FxService()
        assert svc.source_mode == "stub"

    def test_stub_fallback_rates_positive(self) -> None:
        """In modalità stub tutti i tassi EUR/X sono > 0."""
        with patch("shared.fx_service._fetch_live_eur_rates", return_value=None):
            svc = FxService()
        assert svc.source_mode == "stub"
        for currency in [Currency.USD, Currency.GBP, Currency.CHF, Currency.JPY]:
            rate = svc.get_rate(Currency.EUR, currency)
            assert rate.rate > Decimal("0"), f"stub rate for {currency} not positive"

    def test_same_currency_source_reflects_mode(self) -> None:
        svc = FxService()
        rate = svc.get_rate(Currency.EUR, Currency.EUR)
        assert rate.rate == Decimal("1.0")
        assert rate.source in ("live", "stub")

    def test_ttl_triggers_refresh(self) -> None:
        """Dopo scadenza TTL, _refresh viene chiamato al prossimo get_rate."""
        import time

        svc = FxService()
        svc._last_fetch_ts = time.monotonic() - 1000  # force TTL expiry
        with patch.object(svc, "_refresh") as mock_refresh:
            mock_refresh.side_effect = lambda: None  # noop
            svc.get_rate(Currency.EUR, Currency.USD)
            mock_refresh.assert_called_once()


@pytest.mark.integration
class TestFxServiceLiveIntegration:
    """Tests that hit yfinance — excluded from normal runs, use -m integration."""

    def test_live_rates_fetched(self) -> None:
        """Verifica che yfinance restituisca tassi reali > 0 per tutti i pair."""
        import shared.fx_service as fx_mod

        rates = fx_mod._fetch_live_eur_rates()
        assert rates is not None, "yfinance non ha restituito tassi live"
        for currency, rate in rates.items():
            assert rate > Decimal("0"), f"tasso negativo per {currency}"

    def test_live_service_source_is_live(self) -> None:
        """In ambiente con rete, source_mode deve essere 'live'."""
        svc = FxService()
        assert svc.source_mode == "live"
        rate = svc.get_rate(Currency.EUR, Currency.USD)
        assert float(rate.rate) > 0.5  # EUR/USD non può essere < 0.5
