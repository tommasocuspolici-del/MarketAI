"""Tax calculator — facade that delegates to per-country rules."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from personal.tax.rules.eu_generic import EUGenericTaxRules
from personal.tax.rules.italy import ItalyTaxRules, TaxableEvent
from shared.exceptions import PersonalError
from shared.logger import get_logger

__version__ = "6.0.0"

__all__ = ["AnnualTaxReport", "TaxCalculator", "TaxRegime"]

log = get_logger(__name__)


class TaxRegime(StrEnum):
    """Supported tax regimes."""

    ITALY = "italy"
    EU_GENERIC = "eu_generic"


@dataclass(frozen=True, slots=True)
class AnnualTaxReport:
    """End-of-year tax computation summary."""

    profile_id: str
    fiscal_year: int
    regime: TaxRegime
    total_gain: float
    total_loss: float
    net_taxable: float
    tax_capital: float
    tax_dividends: float
    tax_owed: float
    remaining_carry_forward: float
    n_events: int


class TaxCalculator:
    """Facade dispatching to per-country rules (Rule 18: Currency esplicita)."""

    def __init__(self, regime: TaxRegime = TaxRegime.ITALY) -> None:
        self._regime = regime

    def compute_annual_report(
        self,
        profile_id: str,
        fiscal_year: int,
        events: list[TaxableEvent],
        carried_forward_losses: float = 0.0,
    ) -> AnnualTaxReport:
        """Compute the annual tax report for a list of events.

        Args:
            profile_id: Investor profile.
            fiscal_year: Year (e.g. 2025).
            events: Realized taxable events of the year.
            carried_forward_losses: Loss carry-forward from previous years
                (Italian rule: 4 years).
        """
        if not 2000 <= fiscal_year <= 2100:
            raise PersonalError(f"fiscal_year out of range: {fiscal_year}")

        # Filtra eventi per anno fiscale (sicurezza)
        events_in_year = [e for e in events if e.realized_at.year == fiscal_year]

        if self._regime == TaxRegime.ITALY:
            summary = ItalyTaxRules.compute_annual_tax(
                events_in_year, carried_forward_losses=carried_forward_losses
            )
        else:
            # EU generic fallback: gestione semplificata (no loss carry forward)
            gains = [e.gain for e in events_in_year if not e.is_dividend]
            divs = [e.gain for e in events_in_year if e.is_dividend]
            eu_summary = EUGenericTaxRules.compute_annual_summary(gains, divs)
            summary = {
                "total_gain": float(sum(g for g in gains if g > 0)),
                "total_loss": float(-sum(g for g in gains if g < 0)),
                "net_taxable": float(max(sum(gains), 0.0)),
                "tax_capital": eu_summary["tax_capital"],
                "tax_dividends": eu_summary["tax_dividends"],
                "tax_owed": eu_summary["tax_owed"],
                "remaining_carry_forward": 0.0,
            }

        log.info(
            "tax.annual_report",
            profile_id=profile_id,
            year=fiscal_year,
            regime=self._regime.value,
            tax_owed=round(summary["tax_owed"], 2),
        )

        return AnnualTaxReport(
            profile_id=profile_id,
            fiscal_year=fiscal_year,
            regime=self._regime,
            total_gain=summary["total_gain"],
            total_loss=summary["total_loss"],
            net_taxable=summary["net_taxable"],
            tax_capital=summary["tax_capital"],
            tax_dividends=summary["tax_dividends"],
            tax_owed=summary["tax_owed"],
            remaining_carry_forward=summary["remaining_carry_forward"],
            n_events=len(events_in_year),
        )
