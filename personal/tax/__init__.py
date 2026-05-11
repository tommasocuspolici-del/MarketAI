"""Tax sub-package — capital gain calculator (IT regime + EU generic)."""
from __future__ import annotations

from personal.tax.calculator import AnnualTaxReport, TaxCalculator, TaxRegime
from personal.tax.rules.italy import ItalyTaxRules, ITAssetClass, TaxableEvent

__version__ = "6.0.0"

__all__ = [
    "AnnualTaxReport",
    "ITAssetClass",
    "ItalyTaxRules",
    "TaxCalculator",
    "TaxRegime",
    "TaxableEvent",
]
