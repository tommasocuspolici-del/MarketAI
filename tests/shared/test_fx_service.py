"""Tests for shared.fx_service."""
from __future__ import annotations

from decimal import Decimal

import pytest

from shared.exceptions import DataError
from shared.fx_service import FxService
from shared.types import Currency, Money


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
        # USD → GBP passa via EUR
        rate = svc.get_rate(Currency.USD, Currency.GBP)
        assert rate.source == "triangulated"
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
        # BTC è nella enum ma non nel _STUB_EUR_RATES
        with pytest.raises(DataError):
            svc.get_rate(Currency.EUR, Currency.BTC)

    def test_set_rate_overrides(self) -> None:
        svc = FxService()
        custom = Decimal("2.0")
        svc.set_rate(Currency.EUR, Currency.USD, custom)
        rate = svc.get_rate(Currency.EUR, Currency.USD)
        assert rate.rate == custom
