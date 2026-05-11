"""Core type definitions shared across all layers.

All monetary amounts must carry an explicit Currency (Rule 18).
All datetimes must be UTC-aware (Rule 19).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final

__version__ = "6.0.0"

__all__ = [
    "AssetClass",
    "Currency",
    "DataSource",
    "HealthState",
    "MarketRegime",
    "Money",
    "OrderSide",
    "TimeFrame",
    "ensure_utc",
    "now_utc",
]


# ═══════════════════════════════════════════════════════════════════════════
# Currency (Rule 18)
# ═══════════════════════════════════════════════════════════════════════════
class Currency(StrEnum):
    """Supported currencies. Any monetary amount must carry one of these."""

    EUR = "EUR"
    USD = "USD"
    GBP = "GBP"
    CHF = "CHF"
    JPY = "JPY"
    CNY = "CNY"
    AUD = "AUD"
    CAD = "CAD"
    # Crypto (quotate, non fiat)
    BTC = "BTC"
    ETH = "ETH"


# ═══════════════════════════════════════════════════════════════════════════
# Time frames
# ═══════════════════════════════════════════════════════════════════════════
class TimeFrame(StrEnum):
    """Supported bar timeframes for OHLCV data."""

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1w"
    MO1 = "1mo"


# ═══════════════════════════════════════════════════════════════════════════
# Asset classes
# ═══════════════════════════════════════════════════════════════════════════
class AssetClass(StrEnum):
    """Asset classification used by InvestorProfile and Allocator."""

    EQUITY = "equity"
    BONDS = "bonds"
    ETF = "etf"
    CASH = "cash"
    COMMODITIES = "commodities"
    REAL_ESTATE = "real_estate"
    CRYPTO = "crypto"
    FOREX = "forex"
    OPTIONS = "options"
    FUTURES = "futures"


# ═══════════════════════════════════════════════════════════════════════════
# Orders / trades
# ═══════════════════════════════════════════════════════════════════════════
class OrderSide(StrEnum):
    """Side of an order or position."""

    LONG = "long"
    SHORT = "short"
    BUY = "buy"
    SELL = "sell"


# ═══════════════════════════════════════════════════════════════════════════
# Market regime (HMM output)
# ═══════════════════════════════════════════════════════════════════════════
class MarketRegime(StrEnum):
    """Market regime as detected by the HMM model."""

    BULL = "bull"
    BEAR = "bear"
    TRANSITION = "transition"
    STRESS = "stress"


# ═══════════════════════════════════════════════════════════════════════════
# Data sources
# ═══════════════════════════════════════════════════════════════════════════
class DataSource(StrEnum):
    """Identifiers for external data sources. Must match keys in rate_limits.yaml."""

    YAHOO_FINANCE = "yahoo_finance"
    FINNHUB = "finnhub"
    ALPHA_VANTAGE = "alpha_vantage"
    FRED = "fred"
    SEC_EDGAR = "sec_edgar"
    ECB = "ecb"
    EUROSTAT = "eurostat"
    WORLD_BANK = "world_bank"
    BLS = "bls"
    IMF = "imf"
    COINGECKO = "coingecko"


# ═══════════════════════════════════════════════════════════════════════════
# Health status (Rule 30)
# ═══════════════════════════════════════════════════════════════════════════
class HealthState(StrEnum):
    """Global system health state."""

    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    DOWN = "down"


# ═══════════════════════════════════════════════════════════════════════════
# Money — type-safe monetary amount
# ═══════════════════════════════════════════════════════════════════════════
_EPSILON: Final[Decimal] = Decimal("0.0000001")


@dataclass(frozen=True, slots=True)
class Money:
    """Immutable monetary amount with explicit currency.

    Uses Decimal internally to avoid floating-point rounding errors
    in financial calculations (Rule 8).
    """

    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        # Normalizzazione: conversione automatica a Decimal se necessaria
        if not isinstance(self.amount, Decimal):
            object.__setattr__(self, "amount", Decimal(str(self.amount)))

    def __str__(self) -> str:
        return f"{self.amount:.2f} {self.currency.value}"

    def __add__(self, other: Money) -> Money:
        self._assert_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._assert_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: int | float | Decimal) -> Money:
        return Money(self.amount * Decimal(str(factor)), self.currency)

    def _assert_same_currency(self, other: Money) -> None:
        # Operazioni cross-currency devono passare per fx_service (Regola 18)
        if self.currency != other.currency:
            raise ValueError(
                f"Cannot combine {self.currency.value} and {other.currency.value} "
                f"directly. Use shared.fx_service for conversions."
            )

    def is_positive(self) -> bool:
        return self.amount > _EPSILON

    def is_zero(self) -> bool:
        return abs(self.amount) <= _EPSILON


# ═══════════════════════════════════════════════════════════════════════════
# Datetime helpers (Rule 19)
# ═══════════════════════════════════════════════════════════════════════════
def now_utc() -> datetime:
    """Return the current UTC-aware datetime."""
    return datetime.now(UTC)


def ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is UTC-aware. Naive datetimes are assumed UTC."""
    if dt.tzinfo is None:
        # Normalizzazione: i datetime naive sono considerati UTC per convenzione
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
