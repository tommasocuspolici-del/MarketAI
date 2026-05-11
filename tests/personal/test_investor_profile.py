"""Tests for personal.investor_profile."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from personal.investor_profile import (
    InvestmentHorizon,
    InvestorProfile,
    ProfileLoader,
    RiskTolerance,
    SuitabilityChecker,
)
from shared.exceptions import ProfileNotFoundError, ProfileSuitabilityError


def _sample_profile(profile_id: str = "p_test") -> InvestorProfile:
    return InvestorProfile(
        profile_id=profile_id,
        name="Mario Rossi",
        risk_tolerance=RiskTolerance.MODERATE,
        max_drawdown_pct=0.20,
        investment_horizon=InvestmentHorizon.LONG,
        horizon_years=15,
        liquidity_reserve_months=6,
        financial_knowledge=3,
        allowed_asset_classes=["equity", "etf", "bonds"],
        excluded_sectors=["tobacco", "weapons"],
        excluded_countries=["RU"],
        base_currency="EUR",
    )


# ═══════════════════════════════════════════════════════════════════════════
# Profile model
# ═══════════════════════════════════════════════════════════════════════════
class TestInvestorProfile:
    def test_construction(self) -> None:
        p = _sample_profile()
        assert p.profile_id == "p_test"
        assert p.risk_tolerance == RiskTolerance.MODERATE
        assert p.max_drawdown_pct == 0.20

    def test_can_hold(self) -> None:
        p = _sample_profile()
        assert p.can_hold("equity") is True
        assert p.can_hold("EQUITY") is True   # case-insensitive
        assert p.can_hold("crypto") is False

    def test_is_suitable_drawdown(self) -> None:
        p = _sample_profile()
        assert p.is_suitable_drawdown(0.15) is True
        assert p.is_suitable_drawdown(0.25) is False
        # Negativo è interpretato come absolute
        assert p.is_suitable_drawdown(-0.15) is True

    def test_excludes_sector(self) -> None:
        p = _sample_profile()
        assert p.excludes_sector("tobacco") is True
        assert p.excludes_sector("Tobacco") is True
        assert p.excludes_sector("technology") is False

    def test_to_db_dict_and_back(self) -> None:
        original = _sample_profile()
        as_dict = original.to_db_dict()
        # JSON fields persistiti come stringa
        assert isinstance(as_dict["allowed_asset_classes"], str)
        # Round-trip
        # Aggiungi i campi created_at/updated_at che il DB normalmente fornisce
        as_dict["created_at"] = "2025-01-01"
        as_dict["updated_at"] = "2025-01-01"
        recovered = InvestorProfile.from_db_row(as_dict)
        assert recovered.profile_id == original.profile_id
        assert recovered.allowed_asset_classes == original.allowed_asset_classes

    def test_invalid_drawdown_pct_raises(self) -> None:
        with pytest.raises(ValidationError):
            InvestorProfile(
                profile_id="p", name="X",
                risk_tolerance=RiskTolerance.MODERATE,
                max_drawdown_pct=1.5,  # > 1.0
                investment_horizon=InvestmentHorizon.LONG,
                horizon_years=10, liquidity_reserve_months=6,
                financial_knowledge=3,
            )


# ═══════════════════════════════════════════════════════════════════════════
# ProfileLoader (SQLite)
# ═══════════════════════════════════════════════════════════════════════════
class TestProfileLoader:
    def test_save_and_load(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        loader = ProfileLoader(client=personal_sqlite_client)
        original = _sample_profile()
        loader.save(original)
        loaded = loader.load("p_test")
        assert loaded.profile_id == "p_test"
        assert loaded.risk_tolerance == RiskTolerance.MODERATE
        assert loaded.allowed_asset_classes == ["equity", "etf", "bonds"]

    def test_load_missing_raises(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        loader = ProfileLoader(client=personal_sqlite_client)
        with pytest.raises(ProfileNotFoundError):
            loader.load("nonexistent")

    def test_exists(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        loader = ProfileLoader(client=personal_sqlite_client)
        loader.save(_sample_profile())
        assert loader.exists("p_test") is True
        assert loader.exists("ghost") is False

    def test_save_idempotent_update(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        loader = ProfileLoader(client=personal_sqlite_client)
        loader.save(_sample_profile())
        # Save again with modified field — UPDATE path
        modified = _sample_profile().model_copy(update={"name": "Modified"})
        loader.save(modified)
        assert loader.load("p_test").name == "Modified"
        assert len(loader.list_all()) == 1

    def test_list_all(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        loader = ProfileLoader(client=personal_sqlite_client)
        loader.save(_sample_profile("p1"))
        loader.save(_sample_profile("p2"))
        all_profiles = loader.list_all()
        assert len(all_profiles) == 2

    def test_delete(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        loader = ProfileLoader(client=personal_sqlite_client)
        loader.save(_sample_profile())
        loader.delete("p_test")
        assert loader.exists("p_test") is False


# ═══════════════════════════════════════════════════════════════════════════
# SuitabilityChecker (Rule 22)
# ═══════════════════════════════════════════════════════════════════════════
class TestSuitabilityChecker:
    def test_suitable_instrument(self) -> None:
        checker = SuitabilityChecker(_sample_profile())
        result = checker.check_instrument(
            ticker="AAPL", asset_class="equity",
            expected_max_drawdown=0.15,
            sector="technology", country="US",
        )
        assert result.is_suitable
        assert result.reasons == []

    def test_rejects_unallowed_asset_class(self) -> None:
        checker = SuitabilityChecker(_sample_profile())
        result = checker.check_instrument(
            ticker="BTC", asset_class="crypto",
            expected_max_drawdown=0.30,
        )
        assert not result.is_suitable
        assert any("crypto" in r for r in result.reasons)

    def test_rejects_excessive_drawdown(self) -> None:
        checker = SuitabilityChecker(_sample_profile())
        result = checker.check_instrument(
            ticker="X", asset_class="equity",
            expected_max_drawdown=0.30,
        )
        assert not result.is_suitable
        assert any("drawdown" in r.lower() for r in result.reasons)

    def test_rejects_excluded_sector(self) -> None:
        checker = SuitabilityChecker(_sample_profile())
        result = checker.check_instrument(
            ticker="X", asset_class="equity",
            expected_max_drawdown=0.10,
            sector="tobacco",
        )
        assert not result.is_suitable

    def test_rejects_excluded_country(self) -> None:
        checker = SuitabilityChecker(_sample_profile())
        result = checker.check_instrument(
            ticker="X", asset_class="equity",
            expected_max_drawdown=0.10,
            country="RU",
        )
        assert not result.is_suitable

    def test_assert_suitable_raises_on_blocker(self) -> None:
        checker = SuitabilityChecker(_sample_profile())
        with pytest.raises(ProfileSuitabilityError):
            checker.assert_suitable(
                ticker="BTC", asset_class="crypto",
            )

    def test_assert_suitable_silent_on_pass(self) -> None:
        checker = SuitabilityChecker(_sample_profile())
        checker.assert_suitable(  # non solleva
            ticker="VWCE", asset_class="etf",
            expected_max_drawdown=0.15,
        )
