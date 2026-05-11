"""Tests for personal.networth."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from personal.investor_profile import (
    InvestmentHorizon,
    InvestorProfile,
    ProfileLoader,
    RiskTolerance,
)
from personal.networth import (
    Asset,
    AssetType,
    Liability,
    NetWorthSnapshot,
    NetWorthTracker,
)


def _create_profile(client) -> str:  # type: ignore[no-untyped-def]
    profile = InvestorProfile(
        profile_id="p_nw",
        name="NW Tester",
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
# Asset / Liability models
# ═══════════════════════════════════════════════════════════════════════════
class TestAssetLiability:
    def test_asset_construction(self) -> None:
        a = Asset(
            profile_id="p", asset_type=AssetType.EQUITY,
            name="Apple", current_value=10_000.0,
        )
        assert a.asset_type == AssetType.EQUITY

    def test_liability_construction(self) -> None:
        liab = Liability(
            profile_id="p", name="Mortgage", current_balance=150_000.0,
        )
        assert liab.current_balance == 150_000.0

    def test_negative_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Asset(
                profile_id="p", asset_type=AssetType.CASH,
                name="X", current_value=-100.0,
            )


# ═══════════════════════════════════════════════════════════════════════════
# NetWorthTracker
# ═══════════════════════════════════════════════════════════════════════════
class TestNetWorthTracker:
    def test_add_and_list_assets(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        pid = _create_profile(personal_sqlite_client)
        tracker = NetWorthTracker(client=personal_sqlite_client)
        tracker.add_asset(Asset(
            profile_id=pid, asset_type=AssetType.CASH,
            name="Conto Corrente", current_value=5_000,
        ))
        tracker.add_asset(Asset(
            profile_id=pid, asset_type=AssetType.EQUITY,
            name="ETF VWCE", current_value=20_000,
        ))
        assets = tracker.list_assets(pid)
        assert len(assets) == 2

    def test_compute_snapshot(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        pid = _create_profile(personal_sqlite_client)
        tracker = NetWorthTracker(client=personal_sqlite_client)
        tracker.add_asset(Asset(
            profile_id=pid, asset_type=AssetType.CASH,
            name="Conto", current_value=5_000,
        ))
        tracker.add_asset(Asset(
            profile_id=pid, asset_type=AssetType.EQUITY,
            name="ETF", current_value=15_000,
        ))
        tracker.add_liability(Liability(
            profile_id=pid, name="Mutuo", current_balance=10_000,
        ))
        snapshot = tracker.compute_current_snapshot(pid)
        assert isinstance(snapshot, NetWorthSnapshot)
        assert snapshot.total_assets == 20_000
        assert snapshot.total_liabilities == 10_000
        assert snapshot.net_worth == 10_000
        assert snapshot.is_positive
        # Breakdown
        assert snapshot.breakdown["cash"] == 5_000
        assert snapshot.breakdown["equity"] == 15_000

    def test_save_and_list_snapshots(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        pid = _create_profile(personal_sqlite_client)
        tracker = NetWorthTracker(client=personal_sqlite_client)
        tracker.add_asset(Asset(
            profile_id=pid, asset_type=AssetType.CASH,
            name="X", current_value=1_000,
        ))
        snap = tracker.compute_current_snapshot(pid)
        tracker.save_snapshot(snap)

        history = tracker.list_snapshots(pid)
        assert len(history) == 1
        assert history[0].net_worth == 1_000

    def test_negative_net_worth(self, personal_sqlite_client) -> None:  # type: ignore[no-untyped-def]
        pid = _create_profile(personal_sqlite_client)
        tracker = NetWorthTracker(client=personal_sqlite_client)
        tracker.add_asset(Asset(
            profile_id=pid, asset_type=AssetType.CASH,
            name="X", current_value=1_000,
        ))
        tracker.add_liability(Liability(
            profile_id=pid, name="Big debt", current_balance=5_000,
        ))
        snap = tracker.compute_current_snapshot(pid)
        assert snap.net_worth == -4_000
        assert not snap.is_positive
