"""Suitability checker — enforces Rule 22.

Every concrete suggestion produced by the personal layer must pass
through ``check_instrument()`` to ensure it's compatible with the
investor's profile (asset class allowed, drawdown tolerable, sectors/
countries not excluded).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from shared.exceptions import ProfileSuitabilityError
from shared.logger import get_logger

if TYPE_CHECKING:
    from personal.investor_profile.profile_model import InvestorProfile

__version__ = "6.0.0"

__all__ = ["SuitabilityChecker", "SuitabilityResult"]

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SuitabilityResult:
    """Outcome of a suitability check."""

    is_suitable: bool
    profile_id: str
    instrument: str
    reasons: list[str]

    @property
    def has_blockers(self) -> bool:
        return not self.is_suitable


class SuitabilityChecker:
    """Filter suggestions through an InvestorProfile (Rule 22)."""

    def __init__(self, profile: InvestorProfile) -> None:
        self._profile = profile

    @property
    def profile(self) -> InvestorProfile:
        return self._profile

    def check_instrument(
        self,
        ticker: str,
        asset_class: str,
        expected_max_drawdown: float = 0.0,
        sector: str | None = None,
        country: str | None = None,
    ) -> SuitabilityResult:
        """Run all suitability checks on a candidate instrument.

        Args:
            ticker: Instrument identifier (for the result).
            asset_class: ``equity``/``bonds``/``etf``/``cash``/``crypto`` etc.
            expected_max_drawdown: Expected max DD (positive float).
            sector: Optional sector classification.
            country: Optional country/region classification.

        Returns:
            SuitabilityResult with ``is_suitable`` and human-readable reasons.
        """
        reasons: list[str] = []

        # Asset class allowed?
        if not self._profile.can_hold(asset_class):
            reasons.append(
                f"asset class '{asset_class}' not in allowed list "
                f"({', '.join(self._profile.allowed_asset_classes)})"
            )

        # Drawdown tolerance
        if expected_max_drawdown > 0 and not self._profile.is_suitable_drawdown(
            expected_max_drawdown
        ):
            reasons.append(
                f"expected max drawdown {expected_max_drawdown:.1%} "
                f"exceeds tolerance {self._profile.max_drawdown_pct:.1%}"
            )

        # Sector exclusion
        if sector and self._profile.excludes_sector(sector):
            reasons.append(f"sector '{sector}' is excluded by profile")

        # Country exclusion
        if country and self._profile.excludes_country(country):
            reasons.append(f"country '{country}' is excluded by profile")

        is_suitable = not reasons
        result = SuitabilityResult(
            is_suitable=is_suitable,
            profile_id=self._profile.profile_id,
            instrument=ticker,
            reasons=reasons,
        )

        if not is_suitable:
            log.info(
                "suitability.rejected",
                profile_id=self._profile.profile_id,
                ticker=ticker,
                reasons=reasons,
            )
        return result

    def assert_suitable(
        self,
        ticker: str,
        asset_class: str,
        expected_max_drawdown: float = 0.0,
        sector: str | None = None,
        country: str | None = None,
    ) -> None:
        """Raise ProfileSuitabilityError if the instrument is unsuitable.

        Use this at the entry point of any function that produces a
        concrete suggestion.
        """
        result = self.check_instrument(
            ticker, asset_class, expected_max_drawdown, sector, country
        )
        if result.has_blockers:
            raise ProfileSuitabilityError(
                instrument=ticker,
                profile_id=self._profile.profile_id,
                reason="; ".join(result.reasons),
            )
