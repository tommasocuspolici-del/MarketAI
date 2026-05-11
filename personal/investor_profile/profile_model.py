"""Investor profile model — the SINGLE source of truth for filtering
all suggestions in the personal layer (Rule 22).

The profile is stored in SQLite (table ``investor_profiles``) and loaded
once per session. Frozen Pydantic for immutability during analysis.
"""
from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__version__ = "6.0.0"

__all__ = [
    "InvestmentHorizon",
    "InvestorProfile",
    "RiskTolerance",
]


class RiskTolerance(StrEnum):
    """Risk tolerance levels with associated max drawdown thresholds."""

    CONSERVATIVE = "conservative"            # Max DD 10%
    MODERATE = "moderate"                    # Max DD 20%
    AGGRESSIVE = "aggressive"                # Max DD 35%
    VERY_AGGRESSIVE = "very_aggressive"      # Max DD 50%+


class InvestmentHorizon(StrEnum):
    """Investment horizon buckets."""

    SHORT = "short"          # < 2 anni
    MEDIUM = "medium"        # 2-7 anni
    LONG = "long"            # 7-15 anni
    VERY_LONG = "very_long"  # > 15 anni


class InvestorProfile(BaseModel):
    """Investor profile. Immutable during a session.

    Every suggestion produced by the personal layer MUST be filtered
    through this profile (Rule 22).
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    profile_id: str
    name: str

    # Rischio
    risk_tolerance: RiskTolerance
    max_drawdown_pct: float = Field(ge=0.0, le=1.0)

    # Orizzonte
    investment_horizon: InvestmentHorizon
    horizon_years: int = Field(ge=1, le=40)

    # Liquidità
    liquidity_reserve_months: int = Field(
        ge=0,
        le=24,
        description="Mesi di spese coperte da riserva liquida prima di investire",
    )

    # Conoscenza finanziaria
    financial_knowledge: int = Field(
        ge=1, le=5, description="1=principiante, 5=esperto"
    )

    # Asset class consentite
    allowed_asset_classes: list[str] = Field(
        default_factory=lambda: ["equity", "bonds", "etf", "cash"]
    )

    # Vincoli geografici/settoriali
    excluded_sectors: list[str] = Field(default_factory=list)
    excluded_countries: list[str] = Field(default_factory=list)

    # Valuta base
    base_currency: str = "EUR"

    # ─── Suitability checks (Rule 22 helpers) ───────────────────────────
    def can_hold(self, asset_class: str) -> bool:
        """True if asset_class is allowed by the profile."""
        return asset_class.lower() in [a.lower() for a in self.allowed_asset_classes]

    def is_suitable_drawdown(self, expected_max_dd: float) -> bool:
        """True if the expected max drawdown fits within tolerance.

        Args:
            expected_max_dd: Expected max drawdown as a non-negative float
                (e.g. 0.25 for a 25% drawdown). Negative values are
                interpreted as their absolute value (engine convention).
        """
        return abs(expected_max_dd) <= self.max_drawdown_pct

    def excludes_sector(self, sector: str) -> bool:
        """True if the sector is in the exclusion list."""
        return sector.lower() in [s.lower() for s in self.excluded_sectors]

    def excludes_country(self, country: str) -> bool:
        """True if the country is in the exclusion list."""
        return country.lower() in [c.lower() for c in self.excluded_countries]

    # ─── Persistence helpers ───────────────────────────────────────────
    def to_db_dict(self) -> dict[str, Any]:
        """Convert to a dict ready for SQLAlchemy insert."""
        return {
            "profile_id": self.profile_id,
            "name": self.name,
            "risk_tolerance": self.risk_tolerance.value,
            "max_drawdown_pct": self.max_drawdown_pct,
            "investment_horizon": self.investment_horizon.value,
            "horizon_years": self.horizon_years,
            "liquidity_reserve_months": self.liquidity_reserve_months,
            "financial_knowledge": self.financial_knowledge,
            "allowed_asset_classes": json.dumps(self.allowed_asset_classes),
            "excluded_sectors": json.dumps(self.excluded_sectors),
            "excluded_countries": json.dumps(self.excluded_countries),
            "base_currency": self.base_currency,
        }

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> InvestorProfile:
        """Inverse of ``to_db_dict`` — parse a SQLAlchemy row."""
        return cls(
            profile_id=row["profile_id"],
            name=row["name"],
            risk_tolerance=RiskTolerance(row["risk_tolerance"]),
            max_drawdown_pct=row["max_drawdown_pct"],
            investment_horizon=InvestmentHorizon(row["investment_horizon"]),
            horizon_years=row["horizon_years"],
            liquidity_reserve_months=row["liquidity_reserve_months"],
            financial_knowledge=row["financial_knowledge"],
            allowed_asset_classes=json.loads(row["allowed_asset_classes"]),
            excluded_sectors=json.loads(row.get("excluded_sectors") or "[]"),
            excluded_countries=json.loads(row.get("excluded_countries") or "[]"),
            base_currency=row.get("base_currency", "EUR"),
        )
