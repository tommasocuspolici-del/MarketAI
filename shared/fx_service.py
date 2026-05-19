"""FX service: currency conversions (Rule 18).

All cross-currency conversions MUST flow through this module.
Rates are fetched live from yfinance (EUR-pivot pairs) with a 15-minute TTL
and a silent fallback to static stub rates when yfinance is unavailable.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from shared.exceptions import DataError
from shared.logger import get_logger
from shared.types import Currency, Money

__version__ = "7.0.0"

__all__ = ["FxRate", "FxService", "get_fx_service"]

log = get_logger(__name__)

_TTL_S: Final = 900  # 15 minutes — aligns with live_market_ttl_s

# EUR-pivot fallback rates (used when yfinance is unavailable).
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

# yfinance EUR/X forex tickers for each supported currency.
_LIVE_TICKERS: Final[dict[Currency, str]] = {
    Currency.USD: "EURUSD=X",
    Currency.GBP: "EURGBP=X",
    Currency.CHF: "EURCHF=X",
    Currency.JPY: "EURJPY=X",
    Currency.CNY: "EURCNY=X",
    Currency.AUD: "EURAUD=X",
    Currency.CAD: "EURCAD=X",
}


def _fetch_live_eur_rates() -> dict[Currency, Decimal] | None:
    """Download EUR/X rates from yfinance. Returns None on failure."""
    try:
        import yfinance as yf  # lazy import — not always needed at startup

        rates: dict[Currency, Decimal] = {Currency.EUR: Decimal("1.0")}
        for currency, ticker in _LIVE_TICKERS.items():
            try:
                hist = yf.Ticker(ticker).history(period="2d")["Close"]
                if hist.empty:
                    continue
                rate = float(hist.iloc[-1])
                if rate > 0:
                    rates[currency] = Decimal(str(round(rate, 6)))
            except Exception as exc:
                log.debug("fx_service.ticker_error", ticker=ticker, error=str(exc))

        if len(rates) >= 5:  # at least 5/8 pairs fetched successfully
            return rates
        log.warning("fx_service.live_partial", fetched=len(rates))
        return None

    except Exception as exc:
        log.warning("fx_service.live_fetch_error", error=str(exc))
        return None


@dataclass(frozen=True, slots=True)
class FxRate:
    """A single exchange rate observation.

    Convention: ``rate`` is the amount of ``quote`` you get for 1 unit of ``base``.
    ``source`` is ``"live"`` when rates come from yfinance, ``"stub"`` otherwise.
    """

    base: Currency
    quote: Currency
    rate: Decimal
    source: str = "stub"


class FxService:
    """Currency conversion service with live yfinance rates and TTL refresh."""

    def __init__(self) -> None:
        self._rates_eur: dict[Currency, Decimal] = dict(_STUB_EUR_RATES)
        self._source_mode: str = "stub"
        self._last_fetch_ts: float = 0.0
        self._refresh()

    # ── internal ────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        live = _fetch_live_eur_rates()
        if live is not None:
            self._rates_eur = live
            self._source_mode = "live"
            log.info("fx_service.rates_live", pairs=len(live))
        else:
            self._rates_eur = dict(_STUB_EUR_RATES)
            self._source_mode = "stub"
            log.info("fx_service.rates_stub", pairs=len(_STUB_EUR_RATES))
        self._last_fetch_ts = time.monotonic()

    def _maybe_refresh(self) -> None:
        if time.monotonic() - self._last_fetch_ts > _TTL_S:
            self._refresh()

    # ── public API ──────────────────────────────────────────────────────────

    def get_rate(self, base: Currency, quote: Currency) -> FxRate:
        """Return the exchange rate from ``base`` to ``quote``.

        Auto-refreshes live rates when the 15-minute TTL has expired.
        Triangulates via EUR when needed.
        """
        self._maybe_refresh()

        if base == quote:
            return FxRate(base=base, quote=quote, rate=Decimal("1.0"), source=self._source_mode)

        if base not in self._rates_eur or quote not in self._rates_eur:
            raise DataError(f"FX rate not available for {base.value}/{quote.value}")

        eur_per_base = self._rates_eur[base]
        eur_per_quote = self._rates_eur[quote]
        rate = eur_per_quote / eur_per_base
        return FxRate(base=base, quote=quote, rate=rate, source=self._source_mode)

    def convert(self, amount: Money, target: Currency) -> Money:
        """Convert a Money amount to a target currency."""
        if amount.currency == target:
            return amount
        fx = self.get_rate(amount.currency, target)
        converted = amount.amount * fx.rate
        return Money(amount=converted, currency=target)

    def set_rate(self, base: Currency, quote: Currency, rate: Decimal) -> None:
        """Inject or override a specific FX rate (tests + manual overrides)."""
        if base == Currency.EUR:
            self._rates_eur[quote] = rate
        elif quote == Currency.EUR:
            self._rates_eur[base] = Decimal("1.0") / rate
        else:
            log.debug("fx_service.cross_rate_set", base=base.value, quote=quote.value)

    @property
    def source_mode(self) -> str:
        """Returns ``"live"`` or ``"stub"`` depending on active rate source."""
        return self._source_mode


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
