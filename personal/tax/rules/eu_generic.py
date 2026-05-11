"""Generic EU tax rules — simplified flat-rate fallback.

NB: questo è un placeholder per giurisdizioni EU non Italia.
Una vera implementazione richiede regole per-paese (Francia,
Germania, Spagna, Paesi Bassi, ecc.) — fuori scope di v6.0.

Aliquote di riferimento applicate qui (semplificate):
  · Capital gains: 25% (media UE)
  · Dividendi: 25% (media UE)
"""
from __future__ import annotations

from dataclasses import dataclass

__version__ = "6.0.0"

__all__ = ["EU_CAPITAL_GAIN_RATE", "EU_DIVIDEND_RATE", "EUGenericTaxRules"]

EU_CAPITAL_GAIN_RATE: float = 0.25
EU_DIVIDEND_RATE: float = 0.25


@dataclass(frozen=True, slots=True)
class EUGenericTaxRules:
    """Generic EU flat-rate tax computation.

    Use this only as a fallback for EU countries without dedicated rules.
    For accurate Italian tax compliance, use ``ItalyTaxRules`` instead.
    """

    @staticmethod
    def compute_tax(gain: float, is_dividend: bool = False) -> float:
        """Tax owed on a gain. Loss → 0."""
        if gain <= 0:
            return 0.0
        rate = EU_DIVIDEND_RATE if is_dividend else EU_CAPITAL_GAIN_RATE
        return float(gain * rate)

    @staticmethod
    def compute_annual_summary(
        gains: list[float],
        dividends: list[float],
    ) -> dict[str, float]:
        """Aggregate annual tax for a basket of gains/dividends.

        Simple flat-rate model: no loss carry-forward, no asset class
        differentiation. For richer rules, build a country-specific module.
        """
        net_capital_gain = max(sum(gains), 0.0)
        total_div = sum(d for d in dividends if d > 0)
        tax_capital = net_capital_gain * EU_CAPITAL_GAIN_RATE
        tax_div = total_div * EU_DIVIDEND_RATE
        return {
            "tax_capital": float(tax_capital),
            "tax_dividends": float(tax_div),
            "tax_owed": float(tax_capital + tax_div),
        }
