"""Tests for personal.investor_profile.risk_profile_bridge (v7.1.2).

Le funzioni di mapping sono PURE e testabili senza DB. La parte di
persistenza viene testata via mocking di ProfileLoader.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from personal.data_entry.risk_questionnaire import (
    RiskProfile,
    RiskProfileResult,
)
from personal.investor_profile.profile_model import (
    InvestmentHorizon,
    InvestorProfile,
    RiskTolerance,
)
from personal.investor_profile.risk_profile_bridge import (
    DEFAULT_PROFILE_ID,
    questionnaire_to_investor_profile,
    safe_load_investor_profile,
    save_questionnaire_to_investor_profile,
)


def _make_result(
    profile: RiskProfile,
    *,
    capacity: int = 15,
    tolerance: int = 15,
    horizon: int = 10,
    knowledge: int = 10,
    suggested_dd: float = 0.20,
    suggested_eq: float = 0.50,
) -> RiskProfileResult:
    """Builder per fixture RiskProfileResult."""
    return RiskProfileResult(
        total_score=capacity + tolerance + horizon + knowledge,
        dimension_scores={
            "capacity": capacity,
            "tolerance": tolerance,
            "horizon": horizon,
            "knowledge": knowledge,
        },
        profile=profile,
        suggested_max_drawdown_pct=suggested_dd,
        suggested_equity_pct=suggested_eq,
        answers={},
    )


def test_risk_tolerance_mapping_is_one_to_one():
    """I 4 RiskProfile mappano sui 4 RiskTolerance senza ambiguita'."""
    pairs = [
        (RiskProfile.CONSERVATIVE, RiskTolerance.CONSERVATIVE),
        (RiskProfile.MODERATE, RiskTolerance.MODERATE),
        (RiskProfile.AGGRESSIVE, RiskTolerance.AGGRESSIVE),
        (RiskProfile.VERY_AGGRESSIVE, RiskTolerance.VERY_AGGRESSIVE),
    ]
    for q_profile, expected_tol in pairs:
        result = _make_result(q_profile)
        ip = questionnaire_to_investor_profile(result)
        assert ip.risk_tolerance == expected_tol


def test_max_drawdown_propagates():
    """suggested_max_drawdown_pct copiato in max_drawdown_pct (proxy diretto)."""
    result = _make_result(RiskProfile.AGGRESSIVE, suggested_dd=0.42)
    ip = questionnaire_to_investor_profile(result)
    assert ip.max_drawdown_pct == pytest.approx(0.42)


@pytest.mark.parametrize(
    "horizon_score, expected_enum, expected_years",
    [
        (0, InvestmentHorizon.SHORT, 2),
        (5, InvestmentHorizon.SHORT, 2),
        (6, InvestmentHorizon.MEDIUM, 5),
        (10, InvestmentHorizon.MEDIUM, 5),
        (11, InvestmentHorizon.LONG, 10),
        (15, InvestmentHorizon.LONG, 10),
        (16, InvestmentHorizon.VERY_LONG, 20),
        (20, InvestmentHorizon.VERY_LONG, 20),
    ],
)
def test_horizon_buckets(horizon_score, expected_enum, expected_years):
    """Mappatura horizon_score -> bucket discreto."""
    result = _make_result(RiskProfile.MODERATE, horizon=horizon_score)
    ip = questionnaire_to_investor_profile(result)
    assert ip.investment_horizon == expected_enum
    assert ip.horizon_years == expected_years


@pytest.mark.parametrize(
    "capacity_score, expected_months",
    [
        (0, 0),
        (7, 0),
        (8, 3),
        (14, 3),
        (15, 6),
        (21, 6),
        (22, 12),
        (30, 12),
    ],
)
def test_liquidity_reserve_buckets(capacity_score, expected_months):
    """Mappatura capacity_score -> mesi di riserva liquida."""
    result = _make_result(RiskProfile.MODERATE, capacity=capacity_score)
    ip = questionnaire_to_investor_profile(result)
    assert ip.liquidity_reserve_months == expected_months


@pytest.mark.parametrize(
    "knowledge_score, expected_level",
    [
        (0, 1),
        (4, 1),
        (5, 2),
        (8, 2),
        (9, 3),
        (12, 3),
        (13, 4),
        (16, 4),
        (17, 5),
        (20, 5),
    ],
)
def test_knowledge_levels(knowledge_score, expected_level):
    """Mappatura knowledge_score -> 1..5 buckets uniformi."""
    result = _make_result(RiskProfile.MODERATE, knowledge=knowledge_score)
    ip = questionnaire_to_investor_profile(result)
    assert ip.financial_knowledge == expected_level


def test_allowed_asset_classes_progressive():
    """Profili piu' aggressivi sbloccano piu' asset class."""
    conservative = questionnaire_to_investor_profile(
        _make_result(RiskProfile.CONSERVATIVE)
    )
    moderate = questionnaire_to_investor_profile(
        _make_result(RiskProfile.MODERATE)
    )
    aggressive = questionnaire_to_investor_profile(
        _make_result(RiskProfile.AGGRESSIVE)
    )
    very = questionnaire_to_investor_profile(
        _make_result(RiskProfile.VERY_AGGRESSIVE)
    )

    assert "equity" not in conservative.allowed_asset_classes
    assert "equity" in moderate.allowed_asset_classes
    assert "commodities" in aggressive.allowed_asset_classes
    assert "crypto" in very.allowed_asset_classes
    # Cash sempre presente come fallback
    for profile in (conservative, moderate, aggressive, very):
        assert "cash" in profile.allowed_asset_classes


def test_default_profile_id():
    """Convenzione single-user: ID di default e' 'current'."""
    result = _make_result(RiskProfile.MODERATE)
    ip = questionnaire_to_investor_profile(result)
    assert ip.profile_id == DEFAULT_PROFILE_ID
    assert ip.profile_id == "current"


def test_save_calls_loader_save():
    """save_questionnaire_to_investor_profile chiama loader.save()."""
    mock_loader = MagicMock()
    result = _make_result(RiskProfile.MODERATE)
    saved = save_questionnaire_to_investor_profile(
        result, loader=mock_loader
    )
    mock_loader.save.assert_called_once()
    saved_arg = mock_loader.save.call_args[0][0]
    assert isinstance(saved_arg, InvestorProfile)
    assert saved_arg.profile_id == DEFAULT_PROFILE_ID
    assert saved is saved_arg


def test_safe_load_returns_none_on_not_found():
    """safe_load ritorna None invece di sollevare ProfileNotFoundError."""
    from shared.exceptions import ProfileNotFoundError

    mock_loader = MagicMock()
    mock_loader.load.side_effect = ProfileNotFoundError("missing")
    profile = safe_load_investor_profile(loader=mock_loader)
    assert profile is None


def test_safe_load_returns_none_on_db_error():
    """safe_load e' graceful anche con errori DB generici."""
    mock_loader = MagicMock()
    mock_loader.load.side_effect = OSError("DB locked")
    profile = safe_load_investor_profile(loader=mock_loader)
    assert profile is None


def test_safe_load_returns_profile_when_found():
    """Quando il loader trova il profilo, safe_load lo passa attraverso."""
    fake_profile = InvestorProfile(
        profile_id="current",
        name="Test",
        risk_tolerance=RiskTolerance.MODERATE,
        max_drawdown_pct=0.20,
        investment_horizon=InvestmentHorizon.MEDIUM,
        horizon_years=5,
        liquidity_reserve_months=6,
        financial_knowledge=3,
    )
    mock_loader = MagicMock()
    mock_loader.load.return_value = fake_profile
    profile = safe_load_investor_profile(loader=mock_loader)
    assert profile is fake_profile
