"""Tests for personal.alerts.rule_engine (v7.2 fix B8).

Verifica:
  - Generazione alert per regole reali (goal, patrimonio, cashflow)
  - Deduplication 24h
  - Persistenza thresholds
  - mark_read funziona
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from personal.alerts import (
    AlertKind,
    AlertSeverity,
    list_alerts,
    load_thresholds,
    mark_read,
    run_rules,
    save_thresholds,
)
from personal.data_entry.goal_form import (
    GoalCategory,
    GoalInput,
    GoalPriority,
    save_goal,
)
from personal.data_entry.user_data_store import (
    UserDataStore,
    reset_default_store,
)


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    """UserDataStore isolato per test."""
    db_path = tmp_path / "test_alerts.db"
    monkeypatch.setenv("MARKETAI_PERSONAL_DB", str(db_path))
    reset_default_store()
    yield UserDataStore(db_path=db_path)
    reset_default_store()


def _make_risky_goal() -> GoalInput:
    """Goal che richiede >€1000/mese e progresso < 80% → trigger GOAL_AT_RISK."""
    return GoalInput(
        name="Big Goal",
        target_amount=200_000,
        current_amount=10_000,  # 5% progresso
        target_date=date.today() + timedelta(days=365),  # 12 mesi
        category=GoalCategory.PURCHASE,
        priority=GoalPriority.HIGH,
    )


def _make_completed_goal() -> GoalInput:
    """Goal con current >= target → trigger GOAL_ACHIEVED."""
    return GoalInput(
        name="Done Goal",
        target_amount=2_000,
        current_amount=2_500,  # overshoot
        target_date=date.today() + timedelta(days=180),
        category=GoalCategory.TRAVEL,
    )


# ─────────────────────────────────────────────────── thresholds
def test_load_thresholds_returns_defaults_when_empty(isolated_store):
    t = load_thresholds(store=isolated_store)
    assert t["min_alert"] == 0.0
    assert t["target_alert"] == 0.0


def test_save_and_load_thresholds_roundtrip(isolated_store):
    save_thresholds(80_000, 300_000, store=isolated_store)
    t = load_thresholds(store=isolated_store)
    assert t["min_alert"] == 80_000.0
    assert t["target_alert"] == 300_000.0


def test_save_thresholds_rejects_negative(isolated_store):
    with pytest.raises(ValueError):
        save_thresholds(-100, 1000, store=isolated_store)
    with pytest.raises(ValueError):
        save_thresholds(100, -1000, store=isolated_store)


# ─────────────────────────────────────────────────── rules
def test_rule_goal_at_risk_triggers(isolated_store):
    save_goal(_make_risky_goal(), isolated_store)
    new = run_rules(store=isolated_store)
    kinds = {a.kind for a in new}
    assert AlertKind.GOAL_AT_RISK in kinds


def test_rule_goal_achieved_triggers(isolated_store):
    save_goal(_make_completed_goal(), isolated_store)
    new = run_rules(store=isolated_store)
    kinds = {a.kind for a in new}
    assert AlertKind.GOAL_ACHIEVED in kinds


def test_rule_wealth_below_min_triggers_when_threshold_set(isolated_store):
    """Patrimonio = 0 (no asset registrati) e min=80k → CRITICAL."""
    save_thresholds(80_000, 300_000, store=isolated_store)
    new = run_rules(store=isolated_store)
    kinds = {a.kind for a in new}
    assert AlertKind.WEALTH_BELOW_MIN in kinds
    # Deve essere CRITICAL severity
    crit = [a for a in new if a.kind == AlertKind.WEALTH_BELOW_MIN]
    assert crit[0].severity == AlertSeverity.CRITICAL


def test_no_alerts_when_thresholds_zero(isolated_store):
    """Default thresholds = 0 → nessuna allerta WEALTH_*."""
    new = run_rules(store=isolated_store)
    kinds = {a.kind for a in new}
    assert AlertKind.WEALTH_BELOW_MIN not in kinds
    assert AlertKind.WEALTH_ABOVE_TARGET not in kinds


# ─────────────────────────────────────────────────── deduplication
def test_dedup_within_24h_no_duplicates(isolated_store):
    """run_rules() chiamato due volte di seguito non genera duplicati."""
    save_goal(_make_risky_goal(), isolated_store)
    first = run_rules(store=isolated_store)
    assert len(first) >= 1
    second = run_rules(store=isolated_store)
    assert len(second) == 0  # nessuno nuovo


def test_dedup_per_goal_id_for_goal_alerts(isolated_store):
    """GOAL_AT_RISK su goal diversi non si dedupa cross-goal."""
    g1 = _make_risky_goal()
    g2 = GoalInput(
        name="Other Risky",
        target_amount=50_000,
        current_amount=2_000,
        target_date=date.today() + timedelta(days=365),
        category=GoalCategory.PURCHASE,
    )
    save_goal(g1, isolated_store)
    save_goal(g2, isolated_store)
    new = run_rules(store=isolated_store)
    risky = [a for a in new if a.kind == AlertKind.GOAL_AT_RISK]
    # Due goal diversi → due alert AT_RISK distinti
    assert len(risky) == 2
    assert {a.goal_id for a in risky} == {g1.goal_id, g2.goal_id}


# ─────────────────────────────────────────────────── list / mark
def test_list_alerts_returns_persisted(isolated_store):
    save_goal(_make_completed_goal(), isolated_store)
    run_rules(store=isolated_store)
    listed = list_alerts(store=isolated_store)
    assert len(listed) >= 1


def test_mark_read_updates_flag(isolated_store):
    save_goal(_make_completed_goal(), isolated_store)
    run_rules(store=isolated_store)
    listed = list_alerts(store=isolated_store)
    assert listed[0].is_read is False
    ok = mark_read(listed[0].alert_id, store=isolated_store)
    assert ok is True
    listed_after = list_alerts(store=isolated_store)
    assert listed_after[0].is_read is True


def test_mark_read_unknown_id_returns_false(isolated_store):
    assert mark_read("nonexistent_id", store=isolated_store) is False


def test_unread_only_filter(isolated_store):
    save_goal(_make_completed_goal(), isolated_store)
    save_goal(_make_risky_goal(), isolated_store)
    run_rules(store=isolated_store)
    all_alerts = list_alerts(store=isolated_store)
    assert len(all_alerts) >= 2
    # Marca uno come letto
    mark_read(all_alerts[0].alert_id, store=isolated_store)
    unread = list_alerts(unread_only=True, store=isolated_store)
    assert len(unread) == len(all_alerts) - 1
    assert all(not a.is_read for a in unread)
