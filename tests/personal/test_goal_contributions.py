"""Tests for personal.data_entry.goal_form contributions (v7.2 fix B7)."""
from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from personal.data_entry.goal_form import (
    ContributionFrequency,
    ContributionKind,
    GoalCategory,
    GoalInput,
    GoalPriority,
    add_contribution,
    list_contributions,
    list_goals,
    save_goal,
)
from personal.data_entry.user_data_store import (
    UserDataStore,
    reset_default_store,
)


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    """Crea un UserDataStore isolato per ogni test (no condivisione default)."""
    db_path = tmp_path / "test_goals.db"
    monkeypatch.setenv("MARKETAI_PERSONAL_DB", str(db_path))
    reset_default_store()
    yield UserDataStore(db_path=db_path)
    reset_default_store()


def _make_goal(name: str = "Casa", target: float = 100_000) -> GoalInput:
    return GoalInput(
        name=name,
        target_amount=target,
        target_date=date.today() + timedelta(days=365),
        category=GoalCategory.PURCHASE,
        priority=GoalPriority.HIGH,
    )


def test_goal_input_default_no_auto_contribution():
    """Goal creato senza auto-contribution ha defaults coerenti."""
    g = _make_goal()
    assert g.auto_contribution_amount == 0.0
    assert g.auto_contribution_frequency == ContributionFrequency.NONE


def test_auto_contribution_persists_through_payload():
    """Roundtrip to_payload -> from_payload preserva auto_contribution_*."""
    g = _make_goal()
    g_with_auto = g.model_copy(update={
        "auto_contribution_amount": 250.0,
        "auto_contribution_frequency": ContributionFrequency.MONTHLY,
    })
    payload = g_with_auto.to_payload()
    assert payload["auto_contribution_amount"] == 250.0
    assert payload["auto_contribution_frequency"] == "MENSILE"
    g_back = GoalInput.from_payload(payload)
    assert g_back.auto_contribution_amount == 250.0
    assert g_back.auto_contribution_frequency == ContributionFrequency.MONTHLY


def test_from_payload_backward_compat_no_auto_fields():
    """Goal pre-v7.2 (senza auto_*) si carica con defaults senza errore."""
    legacy_payload = {
        "goal_id": "legacy123",
        "name": "Old Goal",
        "category": "ACQUISTO",
        "target_amount": 50_000,
        "current_amount": 5_000,
        "currency": "EUR",
        "target_date": "2027-01-01",
        "priority": "MEDIA",
        "notes": "",
    }
    g = GoalInput.from_payload(legacy_payload)
    assert g.auto_contribution_amount == 0.0
    assert g.auto_contribution_frequency == ContributionFrequency.NONE


def test_add_contribution_deposit_increments_current(isolated_store):
    g = _make_goal()
    save_goal(g, isolated_store)

    updated = add_contribution(
        g.goal_id, 500.0, ContributionKind.DEPOSIT,
        note="primo versamento", store=isolated_store,
    )
    assert updated.current_amount == 500.0

    # Deposito secondo
    updated = add_contribution(
        g.goal_id, 250.0, ContributionKind.DEPOSIT,
        store=isolated_store,
    )
    assert updated.current_amount == 750.0


def test_add_contribution_withdrawal_decrements_current(isolated_store):
    g = _make_goal()
    g_with_balance = g.model_copy(update={"current_amount": 1000.0})
    save_goal(g_with_balance, isolated_store)

    updated = add_contribution(
        g.goal_id, 300.0, ContributionKind.WITHDRAWAL,
        store=isolated_store,
    )
    assert updated.current_amount == 700.0


def test_withdrawal_does_not_go_negative(isolated_store):
    """Prelievo > saldo → current_amount = 0, non negativo."""
    g = _make_goal()
    g_with_balance = g.model_copy(update={"current_amount": 100.0})
    save_goal(g_with_balance, isolated_store)

    updated = add_contribution(
        g.goal_id, 9999.0, ContributionKind.WITHDRAWAL,
        store=isolated_store,
    )
    assert updated.current_amount == 0.0


def test_add_contribution_auto_works_like_deposit(isolated_store):
    """ContributionKind.AUTO incrementa current_amount come DEPOSIT."""
    g = _make_goal()
    save_goal(g, isolated_store)

    updated = add_contribution(
        g.goal_id, 100.0, ContributionKind.AUTO, store=isolated_store
    )
    assert updated.current_amount == 100.0


def test_add_contribution_invalid_amount_raises(isolated_store):
    g = _make_goal()
    save_goal(g, isolated_store)

    with pytest.raises(ValueError, match="amount"):
        add_contribution(
            g.goal_id, 0.0, ContributionKind.DEPOSIT, store=isolated_store
        )
    with pytest.raises(ValueError, match="amount"):
        add_contribution(
            g.goal_id, -100.0, ContributionKind.DEPOSIT, store=isolated_store
        )


def test_add_contribution_unknown_goal_raises(isolated_store):
    with pytest.raises(ValueError, match="non trovato"):
        add_contribution(
            "nonexistent_id", 100.0, ContributionKind.DEPOSIT,
            store=isolated_store,
        )


def test_list_contributions_filter_by_goal_id(isolated_store):
    """Solo i contributi del goal richiesto vengono ritornati."""
    g1 = _make_goal("Goal A")
    g2 = _make_goal("Goal B")
    save_goal(g1, isolated_store)
    save_goal(g2, isolated_store)

    add_contribution(g1.goal_id, 100, ContributionKind.DEPOSIT, store=isolated_store)
    add_contribution(g1.goal_id, 200, ContributionKind.DEPOSIT, store=isolated_store)
    add_contribution(g2.goal_id, 50, ContributionKind.DEPOSIT, store=isolated_store)

    c1 = list_contributions(g1.goal_id, store=isolated_store)
    c2 = list_contributions(g2.goal_id, store=isolated_store)
    assert len(c1) == 2
    assert len(c2) == 1
    assert all(c.goal_id == g1.goal_id for c in c1)


def test_list_contributions_sorted_recent_first(isolated_store):
    """Storico ordinato dalla piu' recente.

    Nota: ``GoalContribution.executed_at`` usa precisione ``timespec="seconds"``
    nella persistenza, quindi serve sleep > 1s tra le aggiunte per
    differenziare i timestamp.
    """
    import time
    g = _make_goal()
    save_goal(g, isolated_store)
    add_contribution(g.goal_id, 1, ContributionKind.DEPOSIT, note="first", store=isolated_store)
    time.sleep(1.05)
    add_contribution(g.goal_id, 2, ContributionKind.DEPOSIT, note="second", store=isolated_store)
    time.sleep(1.05)
    add_contribution(g.goal_id, 3, ContributionKind.DEPOSIT, note="third", store=isolated_store)
    contribs = list_contributions(g.goal_id, store=isolated_store)
    assert len(contribs) == 3
    assert contribs[0].note == "third"
    assert contribs[2].note == "first"
