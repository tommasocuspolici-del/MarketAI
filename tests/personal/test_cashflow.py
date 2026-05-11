"""Tests for personal.cashflow."""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest
from pydantic import ValidationError

from personal.cashflow import (
    CashFlowDirection,
    CashFlowEngine,
    CashFlowEntry,
    CashFlowProjection,
    CashFlowProjector,
)
from personal.investor_profile import (
    InvestmentHorizon,
    InvestorProfile,
    ProfileLoader,
    RiskTolerance,
)


def _create_profile(client) -> str:  # type: ignore[no-untyped-def]
    """Helper: create the test profile FK target."""
    profile = InvestorProfile(
        profile_id="p_cf",
        name="CF Tester",
        risk_tolerance=RiskTolerance.MODERATE,
        max_drawdown_pct=0.20,
        investment_horizon=InvestmentHorizon.LONG,
        horizon_years=15,
        liquidity_reserve_months=6,
        financial_knowledge=3,
    )
    ProfileLoader(client=client).save(profile)
    return profile.profile_id


# ═══════════════════════════════════════════════════════════════════════════
# CashFlowEntry model
# ═══════════════════════════════════════════════════════════════════════════
class TestCashFlowEntry:
    def test_signed_amount_income(self) -> None:
        e = CashFlowEntry(
            profile_id="p1", occurred_at=date(2025, 1, 15),
            direction=CashFlowDirection.IN,
            category="salary", amount=3000.0,
        )
        assert e.signed_amount == 3000.0

    def test_signed_amount_expense(self) -> None:
        e = CashFlowEntry(
            profile_id="p1", occurred_at=date(2025, 1, 15),
            direction=CashFlowDirection.OUT,
            category="rent", amount=1200.0,
        )
        assert e.signed_amount == -1200.0

    def test_amount_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            CashFlowEntry(
                profile_id="p1", occurred_at=date(2025, 1, 1),
                direction=CashFlowDirection.IN,
                category="x", amount=0.0,
            )


# ═══════════════════════════════════════════════════════════════════════════
# CashFlowEngine
# ═══════════════════════════════════════════════════════════════════════════
class TestCashFlowEngine:
    def test_add_and_list_entry(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        pid = _create_profile(personal_sqlite_client)
        engine = CashFlowEngine(client=personal_sqlite_client)
        entry = CashFlowEntry(
            profile_id=pid, occurred_at=date(2025, 1, 15),
            direction=CashFlowDirection.IN,
            category="salary", amount=3000.0,
        )
        engine.add_entry(entry)
        entries = engine.list_entries(pid)
        assert len(entries) == 1
        assert entries[0].amount == 3000.0

    def test_filter_by_direction(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        pid = _create_profile(personal_sqlite_client)
        engine = CashFlowEngine(client=personal_sqlite_client)
        engine.add_entry(CashFlowEntry(
            profile_id=pid, occurred_at=date(2025, 1, 1),
            direction=CashFlowDirection.IN, category="x", amount=100,
        ))
        engine.add_entry(CashFlowEntry(
            profile_id=pid, occurred_at=date(2025, 1, 2),
            direction=CashFlowDirection.OUT, category="y", amount=50,
        ))
        ins = engine.list_entries(pid, direction=CashFlowDirection.IN)
        outs = engine.list_entries(pid, direction=CashFlowDirection.OUT)
        assert len(ins) == 1 and len(outs) == 1

    def test_monthly_summary(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        pid = _create_profile(personal_sqlite_client)
        engine = CashFlowEngine(client=personal_sqlite_client)
        engine.add_entry(CashFlowEntry(
            profile_id=pid, occurred_at=date(2025, 1, 5),
            direction=CashFlowDirection.IN, category="salary", amount=3000,
        ))
        engine.add_entry(CashFlowEntry(
            profile_id=pid, occurred_at=date(2025, 1, 10),
            direction=CashFlowDirection.OUT, category="rent", amount=1200,
        ))
        # Entry in altro mese — non deve comparire
        engine.add_entry(CashFlowEntry(
            profile_id=pid, occurred_at=date(2025, 2, 5),
            direction=CashFlowDirection.IN, category="salary", amount=3000,
        ))
        summary = engine.monthly_summary(pid, year=2025, month=1)
        assert summary["income"] == 3000
        assert summary["expense"] == 1200
        assert summary["net"] == 1800

    def test_delete_entry(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        pid = _create_profile(personal_sqlite_client)
        engine = CashFlowEngine(client=personal_sqlite_client)
        entry = CashFlowEntry(
            profile_id=pid, occurred_at=date(2025, 1, 1),
            direction=CashFlowDirection.IN, category="x", amount=100,
        )
        engine.add_entry(entry)
        engine.delete_entry(entry.entry_id)
        assert engine.list_entries(pid) == []


# ═══════════════════════════════════════════════════════════════════════════
# CashFlowProjector
# ═══════════════════════════════════════════════════════════════════════════
class TestCashFlowProjector:
    def test_empty_history_returns_zero_projection(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        pid = _create_profile(personal_sqlite_client)
        engine = CashFlowEngine(client=personal_sqlite_client)
        projector = CashFlowProjector(engine=engine)
        projection = projector.project(pid, months_ahead=12)
        assert isinstance(projection, CashFlowProjection)
        assert projection.avg_monthly_savings == 0.0
        assert (projection.monthly_income == 0).all()

    def test_projection_with_history(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        pid = _create_profile(personal_sqlite_client)
        engine = CashFlowEngine(client=personal_sqlite_client)
        # Aggiungi 12 mesi di salary + rent (ricorrenti)
        today = date(2025, 4, 1)
        for month in range(1, 13):
            d_in = date(2025, month, 1) if month <= 4 else date(2024, month, 1)
            engine.add_entry(CashFlowEntry(
                profile_id=pid, occurred_at=d_in,
                direction=CashFlowDirection.IN, category="salary",
                amount=3000.0, is_recurring=True,
            ))
            engine.add_entry(CashFlowEntry(
                profile_id=pid, occurred_at=d_in,
                direction=CashFlowDirection.OUT, category="rent",
                amount=1200.0, is_recurring=True,
            ))

        projector = CashFlowProjector(engine=engine)
        projection = projector.project(pid, months_ahead=6, history_months=12, today=today)
        assert projection.avg_monthly_savings > 0
        # Cumulativo crescente
        assert (np.diff(projection.cumulative_net) >= 0).all()
