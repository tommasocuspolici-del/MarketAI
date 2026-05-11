"""Tests for personal.goals."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from personal.goals import (
    FeasibilityResult,
    Goal,
    GoalManager,
    GoalPriority,
    GoalProgress,
    GoalStatus,
    ProgressCalculator,
)
from personal.investor_profile import (
    InvestmentHorizon,
    InvestorProfile,
    ProfileLoader,
    RiskTolerance,
)
from shared.exceptions import GoalError


def _create_profile(client) -> str:  # type: ignore[no-untyped-def]
    profile = InvestorProfile(
        profile_id="p_g",
        name="Goal Tester",
        risk_tolerance=RiskTolerance.MODERATE,
        max_drawdown_pct=0.20,
        investment_horizon=InvestmentHorizon.LONG,
        horizon_years=15,
        liquidity_reserve_months=6,
        financial_knowledge=3,
    )
    ProfileLoader(client=client).save(profile)
    return profile.profile_id


def _sample_goal(profile_id: str = "p_g", **kwargs) -> Goal:  # type: ignore[no-untyped-def]
    defaults = {
        "profile_id": profile_id,
        "name": "House Down Payment",
        "target_amount": 50_000.0,
        "target_date": date.today() + timedelta(days=365 * 5),
    }
    defaults.update(kwargs)
    return Goal(**defaults)


# ═══════════════════════════════════════════════════════════════════════════
# Goal model
# ═══════════════════════════════════════════════════════════════════════════
class TestGoalModel:
    def test_construction(self) -> None:
        g = _sample_goal()
        assert g.target_amount == 50_000.0
        assert g.status == GoalStatus.ACTIVE
        assert g.priority == GoalPriority.MEDIUM

    def test_progress_pct_zero(self) -> None:
        g = _sample_goal()
        assert g.progress_pct == 0.0

    def test_progress_pct_partial(self) -> None:
        g = _sample_goal(current_amount=25_000.0)
        assert g.progress_pct == 0.5

    def test_is_achieved(self) -> None:
        g = _sample_goal(current_amount=50_000.0)
        assert g.is_achieved
        g2 = _sample_goal(current_amount=49_999.0)
        assert not g2.is_achieved

    def test_remaining_amount(self) -> None:
        g = _sample_goal(current_amount=20_000.0)
        assert g.remaining_amount == 30_000.0
        # Anche se sopra-raggiunto, remaining non va negativo
        g2 = _sample_goal(current_amount=70_000.0)
        assert g2.remaining_amount == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# GoalManager (SQLite)
# ═══════════════════════════════════════════════════════════════════════════
class TestGoalManager:
    def test_save_and_get(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        pid = _create_profile(personal_sqlite_client)
        mgr = GoalManager(client=personal_sqlite_client)
        g = _sample_goal(profile_id=pid)
        mgr.save(g)
        loaded = mgr.get(g.goal_id)
        assert loaded.name == g.name
        assert loaded.target_amount == 50_000.0

    def test_get_missing_raises(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        mgr = GoalManager(client=personal_sqlite_client)
        with pytest.raises(GoalError):
            mgr.get("ghost")

    def test_list_for_profile(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        pid = _create_profile(personal_sqlite_client)
        mgr = GoalManager(client=personal_sqlite_client)
        mgr.save(_sample_goal(profile_id=pid, name="A"))
        mgr.save(_sample_goal(profile_id=pid, name="B"))
        goals = mgr.list_for_profile(pid)
        assert len(goals) == 2

    def test_filter_by_status(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        pid = _create_profile(personal_sqlite_client)
        mgr = GoalManager(client=personal_sqlite_client)
        mgr.save(_sample_goal(profile_id=pid, name="Active"))
        mgr.save(_sample_goal(
            profile_id=pid, name="Done",
            current_amount=50_000, status=GoalStatus.ACHIEVED,
        ))
        active = mgr.list_for_profile(pid, status=GoalStatus.ACTIVE)
        achieved = mgr.list_for_profile(pid, status=GoalStatus.ACHIEVED)
        assert len(active) == 1 and len(achieved) == 1

    def test_update_progress_auto_promotes(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        pid = _create_profile(personal_sqlite_client)
        mgr = GoalManager(client=personal_sqlite_client)
        g = _sample_goal(profile_id=pid)
        mgr.save(g)
        # Aggiorna fino al target → auto-promote ad ACHIEVED
        updated = mgr.update_progress(g.goal_id, 50_000)
        assert updated.status == GoalStatus.ACHIEVED
        assert updated.current_amount == 50_000

    def test_update_progress_partial(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        pid = _create_profile(personal_sqlite_client)
        mgr = GoalManager(client=personal_sqlite_client)
        g = _sample_goal(profile_id=pid)
        mgr.save(g)
        updated = mgr.update_progress(g.goal_id, 10_000)
        assert updated.status == GoalStatus.ACTIVE  # non ancora raggiunto

    def test_delete_goal(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        pid = _create_profile(personal_sqlite_client)
        mgr = GoalManager(client=personal_sqlite_client)
        g = _sample_goal(profile_id=pid)
        mgr.save(g)
        mgr.delete(g.goal_id)
        with pytest.raises(GoalError):
            mgr.get(g.goal_id)


# ═══════════════════════════════════════════════════════════════════════════
# ProgressCalculator
# ═══════════════════════════════════════════════════════════════════════════
class TestProgressCalculator:
    def test_compute_progress_basic(self) -> None:
        calc = ProgressCalculator()
        g = _sample_goal(
            target_amount=10_000,
            target_date=date.today() + timedelta(days=365),  # 1 year out
            current_amount=2_000,
        )
        result = calc.compute_progress(g, annual_return=0.05)
        assert isinstance(result, GoalProgress)
        # Required PMT > 0
        assert result.required_monthly_savings > 0
        # Months remaining ~ 12
        assert 11 <= result.months_remaining <= 12

    def test_compute_progress_already_achieved(self) -> None:
        calc = ProgressCalculator()
        g = _sample_goal(
            target_amount=10_000,
            target_date=date.today() + timedelta(days=365),
            current_amount=10_000,
        )
        result = calc.compute_progress(g)
        # Già raggiunto: PMT richiesto è 0
        assert result.required_monthly_savings == 0.0

    def test_check_feasibility_feasible(self) -> None:
        calc = ProgressCalculator()
        g = _sample_goal(
            target_amount=10_000,
            target_date=date.today() + timedelta(days=365 * 5),
        )
        # Con €200/mese su 5 anni a 5% → ~13.6k → fattibile per target 10k
        result = calc.check_feasibility(g, available_monthly_savings=200.0)
        assert isinstance(result, FeasibilityResult)
        assert result.is_feasible

    def test_check_feasibility_infeasible(self) -> None:
        calc = ProgressCalculator()
        g = _sample_goal(
            target_amount=100_000,
            target_date=date.today() + timedelta(days=365),  # 1 year only
        )
        # Con €100/mese in 1 anno: assolutamente infattibile
        result = calc.check_feasibility(g, available_monthly_savings=100.0)
        assert not result.is_feasible
        assert result.shortfall_per_month > 0
