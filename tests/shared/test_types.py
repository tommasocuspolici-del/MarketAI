"""Tests for shared.types (Money, Currency, enums, datetime helpers)."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from shared.types import (
    AssetClass,
    Currency,
    HealthState,
    MarketRegime,
    Money,
    TimeFrame,
    ensure_utc,
    now_utc,
)


class TestCurrency:
    def test_contains_major_currencies(self) -> None:
        assert Currency.EUR.value == "EUR"
        assert Currency.USD.value == "USD"
        assert Currency.BTC.value == "BTC"

    def test_is_string_enum(self) -> None:
        assert Currency.EUR == "EUR"


class TestMoney:
    def test_construction_from_int(self) -> None:
        m = Money(Decimal("100"), Currency.EUR)
        assert m.amount == Decimal("100")
        assert m.currency == Currency.EUR

    def test_string_representation(self) -> None:
        m = Money(Decimal("100.50"), Currency.EUR)
        assert str(m) == "100.50 EUR"

    def test_add_same_currency(self) -> None:
        a = Money(Decimal("100"), Currency.EUR)
        b = Money(Decimal("50"), Currency.EUR)
        assert (a + b).amount == Decimal("150")

    def test_subtract_same_currency(self) -> None:
        a = Money(Decimal("100"), Currency.EUR)
        b = Money(Decimal("30"), Currency.EUR)
        assert (a - b).amount == Decimal("70")

    def test_multiply_by_factor(self) -> None:
        m = Money(Decimal("100"), Currency.EUR)
        assert (m * 2).amount == Decimal("200")
        assert (m * 0.5).amount == Decimal("50.0")

    def test_cross_currency_add_forbidden(self) -> None:
        a = Money(Decimal("100"), Currency.EUR)
        b = Money(Decimal("100"), Currency.USD)
        with pytest.raises(ValueError, match="fx_service"):
            _ = a + b

    def test_is_positive(self) -> None:
        assert Money(Decimal("1"), Currency.EUR).is_positive()
        assert not Money(Decimal("0"), Currency.EUR).is_positive()
        assert not Money(Decimal("-1"), Currency.EUR).is_positive()

    def test_is_zero(self) -> None:
        assert Money(Decimal("0"), Currency.EUR).is_zero()
        assert Money(Decimal("0.00000001"), Currency.EUR).is_zero()
        assert not Money(Decimal("0.01"), Currency.EUR).is_zero()

    def test_frozen(self) -> None:
        m = Money(Decimal("100"), Currency.EUR)
        with pytest.raises(AttributeError):
            m.amount = Decimal("200")  # type: ignore[misc]


class TestDatetimeHelpers:
    def test_now_utc_is_aware(self) -> None:
        n = now_utc()
        assert n.tzinfo is not None
        assert n.tzinfo.utcoffset(n) == UTC.utcoffset(n)

    def test_ensure_utc_naive_to_utc(self) -> None:
        naive = datetime(2026, 1, 1, 12, 0, 0)
        result = ensure_utc(naive)
        assert result.tzinfo is not None

    def test_ensure_utc_already_aware(self) -> None:
        aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = ensure_utc(aware)
        assert result == aware


class TestEnums:
    def test_timeframe_values(self) -> None:
        assert TimeFrame.D1.value == "1d"
        assert TimeFrame.H1.value == "1h"

    def test_asset_class_values(self) -> None:
        assert AssetClass.EQUITY.value == "equity"
        assert AssetClass.BONDS.value == "bonds"

    def test_market_regime_values(self) -> None:
        assert MarketRegime.BULL.value == "bull"
        assert MarketRegime.STRESS.value == "stress"

    def test_health_state_values(self) -> None:
        assert HealthState.OPERATIONAL.value == "operational"
        assert HealthState.DOWN.value == "down"
