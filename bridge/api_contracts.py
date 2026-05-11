"""Bridge API contracts (Rule 21).

ALL communication between engine/ and personal/ MUST go through Pydantic
contracts defined here. Neither layer imports directly from the other.

This module is the single boundary that decouples the two halves of the
application. Changing a contract is a breaking change and requires updating
both sides + contract tests.
"""
from __future__ import annotations

from datetime import date, datetime  # noqa: TC003 — required at runtime by Pydantic
from decimal import Decimal  # noqa: TC003 — required at runtime by Pydantic

from pydantic import BaseModel, ConfigDict, Field

from shared.types import (  # noqa: TC001 — required at runtime by Pydantic
    AssetClass,
    Currency,
    MarketRegime,
)

__version__ = "6.0.0"

__all__ = [
    "ForecastRequest",
    "ForecastScenario",
    "MarketContextForPersonal",
    "PortfolioSnapshotForEngine",
    "PositionContract",
    "StressTestRequest",
    "SuitabilityCheckRequest",
    "SuitabilityCheckResponse",
]


class _StrictModel(BaseModel):
    """Base class: every contract is frozen and forbids extra fields."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


# ═══════════════════════════════════════════════════════════════════════════
# engine → personal : market context
# ═══════════════════════════════════════════════════════════════════════════
class MarketContextForPersonal(_StrictModel):
    """Market data snapshot passed from engine to personal layer.

    Consumed by:
      - wealth_scenarios.simulator   (expected return / volatility)
      - allocator.portfolio_allocator(risk-free rate, regime)
      - suitability_checker          (current market stress level)
    """

    as_of: datetime
    risk_free_rate: float = Field(ge=-0.1, le=1.0)
    equity_expected_return: float = Field(ge=-0.5, le=1.0)
    equity_volatility: float = Field(ge=0.0, le=2.0)
    bond_expected_return: float = Field(ge=-0.2, le=0.5)
    bond_volatility: float = Field(ge=0.0, le=1.0)
    inflation_rate: float = Field(ge=-0.1, le=1.0)
    current_regime: MarketRegime
    vix: float = Field(ge=0.0, le=200.0)


# ═══════════════════════════════════════════════════════════════════════════
# personal → engine : portfolio snapshot
# ═══════════════════════════════════════════════════════════════════════════
class PositionContract(_StrictModel):
    """Single portfolio position, exported to engine for risk analysis."""

    ticker: str
    exchange: str | None = None
    asset_class: AssetClass
    quantity: Decimal
    avg_cost: Decimal
    currency: Currency
    opened_at: datetime


class PortfolioSnapshotForEngine(_StrictModel):
    """Portfolio snapshot sent from personal to engine.

    Engine uses this for:
      - stress testing over user holdings
      - portfolio-level VaR / CVaR
      - beta vs benchmark
    """

    profile_id: str
    captured_at: datetime
    base_currency: Currency
    positions: list[PositionContract]


# ═══════════════════════════════════════════════════════════════════════════
# Suitability check (Rule 22)
# ═══════════════════════════════════════════════════════════════════════════
class SuitabilityCheckRequest(_StrictModel):
    """Request to validate an instrument for a specific investor profile."""

    profile_id: str
    instrument_ticker: str
    asset_class: AssetClass
    expected_max_drawdown_pct: float = Field(ge=0.0, le=1.0)
    annualized_volatility: float = Field(ge=0.0, le=5.0)
    instrument_country: str | None = None
    instrument_sector: str | None = None


class SuitabilityCheckResponse(_StrictModel):
    """Result of a suitability check."""

    is_suitable: bool
    reasons: list[str] = Field(default_factory=list)
    recommended_max_weight_pct: float | None = None


# ═══════════════════════════════════════════════════════════════════════════
# Analysis requests (engine-side)
# ═══════════════════════════════════════════════════════════════════════════
class StressTestRequest(_StrictModel):
    """Request from personal layer to run a personalized stress test."""

    portfolio: PortfolioSnapshotForEngine
    include_historical: bool = True
    include_synthetic: bool = True
    n_synthetic_scenarios: int = Field(default=5, ge=1, le=50)


class ForecastScenario(_StrictModel):
    """Single scenario in a three-scenario forecast (Rule anti-pattern)."""

    scenario: str                    # 'pessimistic' | 'base' | 'optimistic'
    horizon_days: int = Field(ge=1, le=3650)
    expected_return_pct: float
    confidence_lower_pct: float
    confidence_upper_pct: float


class ForecastRequest(_StrictModel):
    """Request a price forecast — always returns 3 scenarios."""

    ticker: str
    horizon_days: int = Field(ge=1, le=3650)
    as_of: date | None = None
