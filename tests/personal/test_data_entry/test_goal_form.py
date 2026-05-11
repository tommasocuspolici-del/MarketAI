"""Test del modulo goal_form."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from personal.data_entry.goal_form import (
    GoalCategory,
    GoalInput,
    GoalPriority,
    delete_goal,
    list_goals,
    save_goal,
)
from personal.data_entry.user_data_store import UserDataStore


@pytest.fixture()
def store(tmp_path: Path) -> UserDataStore:
    """Store SQLite isolato per il test."""
    return UserDataStore(db_path=tmp_path / "test.db")


def test_goal_input_basic_validation() -> None:
    """Schema base si crea senza errori."""
    g = GoalInput(
        name="Casa Milano",
        target_amount=200_000,
        target_date=date.today() + timedelta(days=365 * 3),
    )
    assert g.name == "Casa Milano"
    assert g.target_amount == 200_000
    assert g.priority == GoalPriority.MEDIUM
    assert g.category == GoalCategory.OTHER


def test_goal_input_negative_target_rejected() -> None:
    """target_amount <= 0 deve essere rifiutato."""
    with pytest.raises(ValueError):
        GoalInput(
            name="X",
            target_amount=-100,
            target_date=date.today() + timedelta(days=30),
        )


def test_goal_input_progress_pct() -> None:
    """progress_pct calcolato correttamente."""
    g = GoalInput(
        name="Casa",
        target_amount=100_000,
        current_amount=25_000,
        target_date=date.today() + timedelta(days=365),
    )
    assert g.progress_pct == 0.25
    assert g.remaining_amount == 75_000


def test_goal_input_progress_clamped_to_one() -> None:
    """progress_pct massimo = 1.0."""
    g = GoalInput(
        name="Casa",
        target_amount=100_000,
        current_amount=120_000,  # over target
        target_date=date.today() + timedelta(days=365),
    )
    assert g.progress_pct == 1.0
    assert g.remaining_amount == 0.0


def test_goal_required_monthly_savings() -> None:
    """required_monthly_savings calcolato sui mesi residui."""
    target = date.today() + timedelta(days=365)  # ~12 mesi
    g = GoalInput(
        name="Auto",
        target_amount=12_000,
        current_amount=0,
        target_date=target,
    )
    monthly = g.required_monthly_savings()
    # ~1000/mese (con tolleranza per arrotondamenti mese ≈ 30gg)
    assert 900 < monthly < 1100


def test_goal_serialization_roundtrip() -> None:
    """to_payload + from_payload preservano i campi."""
    original = GoalInput(
        name="Pensione FIRE",
        category=GoalCategory.RETIREMENT,
        target_amount=750_000,
        current_amount=120_000,
        target_date=date(2045, 12, 31),
        priority=GoalPriority.HIGH,
        notes="Capitale = 25x spese annue",
    )
    payload = original.to_payload()
    restored = GoalInput.from_payload(payload)
    assert restored.name == original.name
    assert restored.category == GoalCategory.RETIREMENT
    assert restored.target_amount == 750_000
    assert restored.target_date == date(2045, 12, 31)
    assert restored.priority == GoalPriority.HIGH


def test_goal_persistence_save_and_list(store: UserDataStore) -> None:
    """save_goal poi list_goals ritorna il goal."""
    g = GoalInput(
        name="Vacanza Giappone",
        category=GoalCategory.TRAVEL,
        target_amount=5_000,
        target_date=date.today() + timedelta(days=180),
    )
    save_goal(g, store=store)
    listed = list_goals(store=store)
    assert len(listed) == 1
    assert listed[0].name == "Vacanza Giappone"


def test_goal_delete_works(store: UserDataStore) -> None:
    """delete_goal rimuove correttamente."""
    g = GoalInput(
        name="X",
        target_amount=1000,
        target_date=date.today() + timedelta(days=30),
    )
    save_goal(g, store=store)
    assert delete_goal(g.goal_id, store=store) is True
    assert list_goals(store=store) == []


def test_goal_list_sorted_by_priority(store: UserDataStore) -> None:
    """Goals sono ordinati: HIGH > MEDIUM > LOW."""
    today = date.today()
    save_goal(
        GoalInput(
            name="Bassa",
            target_amount=1000,
            target_date=today + timedelta(days=365),
            priority=GoalPriority.LOW,
        ),
        store=store,
    )
    save_goal(
        GoalInput(
            name="Alta",
            target_amount=1000,
            target_date=today + timedelta(days=365),
            priority=GoalPriority.HIGH,
        ),
        store=store,
    )
    save_goal(
        GoalInput(
            name="Media",
            target_amount=1000,
            target_date=today + timedelta(days=365),
            priority=GoalPriority.MEDIUM,
        ),
        store=store,
    )
    listed = list_goals(store=store)
    names = [g.name for g in listed]
    assert names == ["Alta", "Media", "Bassa"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
