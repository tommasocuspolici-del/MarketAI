"""FX service: currency conversions (Rule 18).

All cross-currency conversions MUST flow through this module.
Real-time rates will be wired in during Phase 3. For now, this module
provides the interface + a stub implementation with a small in-memory
rate table, plus hooks to later plug in yfinance / Finnhub FX feeds.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from shared.exceptions import DataError
from shared.logger import get_logger
from shared.types import Currency, Money

__version__ = "6.0.0"

__all__ = ["FxRate", "FxService", "get_fx_service"]

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Stub rates — PLACEHOLDER only.
# Real rates will be fetched by the fx fetcher (Phase 3).
# ═══════════════════════════════════════════════════════════════════════════
# Tassi base EUR-pivot, validi solo per bootstrap / tests.
_STUB_EUR_RATES: Final[dict[Currency, Decimal]] = {
    Currency.EUR: Decimal("1.0"),
    Currency.USD: Decimal("1.08"),
    Currency.GBP: Decimal("0.85"),
    Currency.CHF: Decimal("0.95"),
    Currency.JPY: Decimal("163.0"),
    Currency.CNY: Decimal("7.80"),
    Currency.AUD: Decimal("1.65"),
    Currency.CAD: Decimal("1.47"),
}


@dataclass(frozen=True, slots=True)
class FxRate:
    """A single exchange rate observation.

    Convention: ``rate`` is the amount of ``quote`` you get for 1 unit of ``base``.
    """

    base: Currency
    quote: Currency
    rate: Decimal
    source: str = "stub"


class FxService:
    """Currency conversion service. Source-agnostic abstraction."""

    def __init__(self) -> None:
        # Cache in-memory. Sostituita da diskcache + fetcher live in Phase 3.
        self._rates_eur: dict[Currency, Decimal] = dict(_STUB_EUR_RATES)
        log.info("fx_service.initialized", rates=len(self._rates_eur), mode="stub")

    def get_rate(self, base: Currency, quote: Currency) -> FxRate:
        """Return the exchange rate from `base` to `quote`.

        Triangulates via EUR when needed.
        """
        if base == quote:
            return FxRate(base=base, quote=quote, rate=Decimal("1.0"))

        if base not in self._rates_eur or quote not in self._rates_eur:
            raise DataError(f"FX rate not available for {base.value}/{quote.value}")

        # Triangolazione via EUR: rate(base/quote) = rate(EUR/quote) / rate(EUR/base)
        eur_per_base = self._rates_eur[base]
        eur_per_quote = self._rates_eur[quote]
        rate = eur_per_quote / eur_per_base
        return FxRate(base=base, quote=quote, rate=rate, source="triangulated")

    def convert(self, amount: Money, target: Currency) -> Money:
        """Convert a Money amount to a target currency."""
        if amount.currency == target:
            return amount
        fx = self.get_rate(amount.currency, target)
        converted = amount.amount * fx.rate
        return Money(amount=converted, currency=target)

    def set_rate(self, base: Currency, quote: Currency, rate: Decimal) -> None:
        """Override or inject an FX rate (tests + future live feed integration)."""
        if base == Currency.EUR:
            self._rates_eur[quote] = rate
        elif quote == Currency.EUR:
            self._rates_eur[base] = Decimal("1.0") / rate
        else:
            # Conserva come tasso cross (gestione semplificata, migliorabile in Phase 3)
            log.debug("fx_service.cross_rate_set", base=base.value, quote=quote.value)


# ═══════════════════════════════════════════════════════════════════════════
# Singleton accessor
# ═══════════════════════════════════════════════════════════════════════════
_INSTANCE: FxService | None = None


def get_fx_service() -> FxService:
    """Return the process-wide FxService singleton."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = FxService()
    return _INSTANCE
