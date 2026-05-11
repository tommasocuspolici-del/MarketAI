"""Tests for personal.tax."""
from __future__ import annotations

from datetime import date

import pytest

from personal.tax import (
    AnnualTaxReport,
    ItalyTaxRules,
    ITAssetClass,
    TaxableEvent,
    TaxCalculator,
    TaxRegime,
)
from personal.tax.rules.eu_generic import EUGenericTaxRules


# ═══════════════════════════════════════════════════════════════════════════
# Italy: tax rates
# ═══════════════════════════════════════════════════════════════════════════
class TestItalyRates:
    def test_equity_rate_26pct(self) -> None:
        assert ItalyTaxRules.get_rate(ITAssetClass.EQUITY) == 0.26

    def test_govt_bond_it_rate_125pct(self) -> None:
        assert ItalyTaxRules.get_rate(ITAssetClass.GOVT_BOND_IT) == 0.125

    def test_dividend_rate_26pct(self) -> None:
        assert ItalyTaxRules.get_rate(ITAssetClass.EQUITY, is_dividend=True) == 0.26


# ═══════════════════════════════════════════════════════════════════════════
# Italy: single event tax computation
# ═══════════════════════════════════════════════════════════════════════════
class TestItalySingleEvent:
    def test_gain_taxed_at_26pct(self) -> None:
        ev = TaxableEvent(
            ticker="AAPL", asset_class=ITAssetClass.EQUITY,
            gain=1000.0, currency="EUR", realized_at=date(2025, 6, 1),
        )
        # 1000 * 26% = 260
        assert ItalyTaxRules.compute_tax_on_event(ev) == 260.0

    def test_loss_zero_tax(self) -> None:
        ev = TaxableEvent(
            ticker="X", asset_class=ITAssetClass.EQUITY,
            gain=-500.0, currency="EUR", realized_at=date(2025, 6, 1),
        )
        assert ItalyTaxRules.compute_tax_on_event(ev) == 0.0

    def test_govt_bond_it_taxed_at_12_5pct(self) -> None:
        ev = TaxableEvent(
            ticker="BTP", asset_class=ITAssetClass.GOVT_BOND_IT,
            gain=1000.0, currency="EUR", realized_at=date(2025, 6, 1),
        )
        # 1000 * 12.5% = 125
        assert ItalyTaxRules.compute_tax_on_event(ev) == 125.0


# ═══════════════════════════════════════════════════════════════════════════
# Italy: annual computation with loss compensation
# ═══════════════════════════════════════════════════════════════════════════
class TestItalyAnnualTax:
    def test_simple_year_no_losses(self) -> None:
        events = [
            TaxableEvent(ticker="A", asset_class=ITAssetClass.EQUITY,
                         gain=1000, currency="EUR", realized_at=date(2025, 3, 1)),
            TaxableEvent(ticker="B", asset_class=ITAssetClass.EQUITY,
                         gain=500, currency="EUR", realized_at=date(2025, 6, 1)),
        ]
        result = ItalyTaxRules.compute_annual_tax(events)
        assert result["total_gain"] == 1500.0
        assert result["total_loss"] == 0.0
        # Tutto tassato a 26%
        assert result["tax_owed"] == pytest.approx(390.0)
        assert result["remaining_carry_forward"] == 0.0

    def test_with_losses_compensation(self) -> None:
        events = [
            TaxableEvent(ticker="A", asset_class=ITAssetClass.EQUITY,
                         gain=1000, currency="EUR", realized_at=date(2025, 3, 1)),
            TaxableEvent(ticker="B", asset_class=ITAssetClass.EQUITY,
                         gain=-300, currency="EUR", realized_at=date(2025, 6, 1)),
        ]
        result = ItalyTaxRules.compute_annual_tax(events)
        # Net taxable = 1000 - 300 = 700; tax = 700 * 26% = 182
        assert result["net_taxable"] == 700.0
        assert result["tax_owed"] == pytest.approx(182.0)

    def test_carry_forward_losses(self) -> None:
        events = [
            TaxableEvent(ticker="A", asset_class=ITAssetClass.EQUITY,
                         gain=500, currency="EUR", realized_at=date(2025, 3, 1)),
        ]
        # Carry-forward maggiore della plusvalenza → niente tax + remaining carry
        result = ItalyTaxRules.compute_annual_tax(events, carried_forward_losses=2000)
        assert result["tax_owed"] == 0.0
        # 2000 - 500 = 1500 ancora compensabile in futuro
        assert result["remaining_carry_forward"] == 1500.0

    def test_dividend_not_compensated_with_capital_loss(self) -> None:
        events = [
            TaxableEvent(ticker="A", asset_class=ITAssetClass.EQUITY,
                         gain=1000, currency="EUR", realized_at=date(2025, 3, 1),
                         is_dividend=True),
            TaxableEvent(ticker="B", asset_class=ITAssetClass.EQUITY,
                         gain=-500, currency="EUR", realized_at=date(2025, 6, 1)),
        ]
        result = ItalyTaxRules.compute_annual_tax(events)
        # Dividend tassato a 26% direttamente: 1000 * 0.26 = 260
        # La perdita da capital gain NON compensa i dividendi (regola IT)
        assert result["tax_dividends"] == pytest.approx(260.0)
        # remaining carry forward = 500 (la minus rimane usabile in futuro)
        assert result["remaining_carry_forward"] == 500.0


# ═══════════════════════════════════════════════════════════════════════════
# EU generic
# ═══════════════════════════════════════════════════════════════════════════
class TestEUGeneric:
    def test_simple_gain(self) -> None:
        assert EUGenericTaxRules.compute_tax(1000.0) == 250.0

    def test_loss_zero(self) -> None:
        assert EUGenericTaxRules.compute_tax(-100.0) == 0.0

    def test_dividend_rate(self) -> None:
        assert EUGenericTaxRules.compute_tax(1000.0, is_dividend=True) == 250.0


# ═══════════════════════════════════════════════════════════════════════════
# TaxCalculator facade
# ═══════════════════════════════════════════════════════════════════════════
class TestTaxCalculator:
    def test_italy_annual_report(self) -> None:
        calc = TaxCalculator(regime=TaxRegime.ITALY)
        events = [
            TaxableEvent(ticker="A", asset_class=ITAssetClass.EQUITY,
                         gain=2000, currency="EUR", realized_at=date(2025, 3, 1)),
            TaxableEvent(ticker="B", asset_class=ITAssetClass.EQUITY,
                         gain=-500, currency="EUR", realized_at=date(2025, 6, 1)),
        ]
        report = calc.compute_annual_report(
            profile_id="p1", fiscal_year=2025, events=events,
        )
        assert isinstance(report, AnnualTaxReport)
        assert report.regime == TaxRegime.ITALY
        # Net = 1500 → tax = 1500 * 26% = 390
        assert report.tax_owed == pytest.approx(390.0)
        assert report.n_events == 2

    def test_eu_generic_report(self) -> None:
        calc = TaxCalculator(regime=TaxRegime.EU_GENERIC)
        events = [
            TaxableEvent(ticker="A", asset_class=ITAssetClass.EQUITY,
                         gain=1000, currency="EUR", realized_at=date(2025, 3, 1)),
        ]
        report = calc.compute_annual_report(
            profile_id="p1", fiscal_year=2025, events=events,
        )
        # 1000 * 25% = 250
        assert report.tax_owed == 250.0

    def test_filters_events_outside_year(self) -> None:
        calc = TaxCalculator()
        events = [
            TaxableEvent(ticker="A", asset_class=ITAssetClass.EQUITY,
                         gain=1000, currency="EUR", realized_at=date(2025, 6, 1)),
            TaxableEvent(ticker="B", asset_class=ITAssetClass.EQUITY,
                         gain=999_999, currency="EUR", realized_at=date(2024, 6, 1)),
        ]
        report = calc.compute_annual_report(
            profile_id="p", fiscal_year=2025, events=events,
        )
        # Solo l'evento del 2025
        assert report.n_events == 1
