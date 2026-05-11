"""Italian tax rules — capital gains 26% + dividend tax 26%.

Riferimenti normativi:
  · D.L. 66/2014: aliquota 26% su rendite finanziarie (in vigore dal 1/7/2014)
  · Esenzione titoli di Stato italiani / sovranazionali whitelist: aliquota 12.5%
  · Compensazione minusvalenze: 4 anni successivi (per esercizio fiscale)

Questa implementazione è semplificata e a scopo educativo.
NON costituisce consulenza fiscale.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

__version__ = "6.0.0"

__all__ = [
    "ITALIAN_CAPITAL_GAIN_RATE",
    "ITALIAN_DIVIDEND_RATE",
    "ITALIAN_GOVT_BOND_RATE",
    "ITAssetClass",
    "ItalyTaxRules",
    "TaxableEvent",
]

# Aliquote fiscali italiane in vigore (Apr 2026)
ITALIAN_CAPITAL_GAIN_RATE: float = 0.26     # 26% rendite finanziarie standard
ITALIAN_DIVIDEND_RATE: float = 0.26          # 26% dividendi su partecipazioni non qualificate
ITALIAN_GOVT_BOND_RATE: float = 0.125         # 12.5% titoli di Stato italiani / whitelist


class ITAssetClass(StrEnum):
    """Asset class to tax rate mapping (Italian regime)."""

    EQUITY = "equity"                    # 26%
    CORPORATE_BOND = "corporate_bond"    # 26%
    GOVT_BOND_IT = "govt_bond_it"        # 12.5% (Italia, whitelist)
    GOVT_BOND_OTHER = "govt_bond_other"  # 26%
    ETF_EQUITY = "etf_equity"            # 26%
    CRYPTO = "crypto"                    # 26% (sopra €2000 plus annua)


@dataclass(frozen=True, slots=True)
class TaxableEvent:
    """A realized tax event (buy + sell pair, dividend, etc.).

    Attributes:
        ticker: Asset identifier.
        asset_class: Italian-classified asset class.
        gain: Realized gain/loss (positive=plusvalenza, negative=minusvalenza).
        currency: Currency the gain was realized in.
        realized_at: Date of realization.
        is_dividend: True if event is a dividend payment.
    """

    ticker: str
    asset_class: ITAssetClass
    gain: float
    currency: str
    realized_at: date
    is_dividend: bool = False


class ItalyTaxRules:
    """Tax computation engine for Italian fiscal regime."""

    @staticmethod
    def get_rate(asset_class: ITAssetClass, is_dividend: bool = False) -> float:
        """Return the applicable tax rate for the given asset class."""
        if asset_class == ITAssetClass.GOVT_BOND_IT:
            return ITALIAN_GOVT_BOND_RATE
        if is_dividend:
            return ITALIAN_DIVIDEND_RATE
        return ITALIAN_CAPITAL_GAIN_RATE

    @staticmethod
    def compute_tax_on_event(event: TaxableEvent) -> float:
        """Tax owed on a single realized event (0 if loss).

        Plusvalenze tassate; minusvalenze NON tassate (e separately
        utilizzabili per compensazione futura).
        """
        if event.gain <= 0:
            return 0.0
        rate = ItalyTaxRules.get_rate(event.asset_class, event.is_dividend)
        return float(event.gain * rate)

    @staticmethod
    def compute_annual_tax(
        events: list[TaxableEvent],
        carried_forward_losses: float = 0.0,
    ) -> dict[str, float]:
        """Compute total annual tax + remaining loss carry-forward.

        Args:
            events: List of taxable events in the fiscal year.
            carried_forward_losses: Minusvalenze accumulate dai 4 anni precedenti.

        Returns:
            dict with keys: total_gain, total_loss, net_taxable,
            tax_owed, remaining_carry_forward.
        """
        # Separa plus e minusvalenze (escludendo dividendi che non si compensano)
        capital_events = [e for e in events if not e.is_dividend]
        dividend_events = [e for e in events if e.is_dividend]

        gains = sum(e.gain for e in capital_events if e.gain > 0)
        losses = -sum(e.gain for e in capital_events if e.gain < 0)

        # Compensazione: usa carry forward + minusvalenze correnti
        total_loss_pool = losses + carried_forward_losses
        net_taxable_capital = max(gains - total_loss_pool, 0.0)
        remaining_carry = max(total_loss_pool - gains, 0.0)

        # Tassazione plusvalenze nette + dividendi (separatamente)
        tax_capital = ItalyTaxRules._weighted_tax(capital_events, net_taxable_capital, gains)
        tax_dividends = sum(
            ItalyTaxRules.compute_tax_on_event(e) for e in dividend_events
        )

        return {
            "total_gain": float(gains),
            "total_loss": float(losses),
            "net_taxable": float(net_taxable_capital),
            "tax_capital": float(tax_capital),
            "tax_dividends": float(tax_dividends),
            "tax_owed": float(tax_capital + tax_dividends),
            "remaining_carry_forward": float(remaining_carry),
        }

    @staticmethod
    def _weighted_tax(
        capital_events: list[TaxableEvent],
        net_taxable: float,
        total_gains: float,
    ) -> float:
        """Apportion tax across asset classes proportional to gain share.

        Necessario perché gli eventi possono mescolare aliquote diverse
        (es. govt bond IT 12.5% vs equity 26%).
        """
        if net_taxable <= 0 or total_gains <= 0:
            return 0.0
        # Per ogni evento positivo, applica la sua aliquota a una quota
        # proporzionale del net_taxable
        tax = 0.0
        for ev in capital_events:
            if ev.gain <= 0:
                continue
            share = ev.gain / total_gains
            taxable_for_this = net_taxable * share
            tax += taxable_for_this * ItalyTaxRules.get_rate(ev.asset_class)
        return tax
