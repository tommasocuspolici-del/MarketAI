"""Test del ManualOverrideStore e UserDataStore."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from personal.data_entry.override_store import ManualOverrideStore
from personal.data_entry.user_data_store import UserDataStore, new_id


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    """Database SQLite temporaneo per ogni test."""
    return tmp_path / "test_personal.db"


# ===================================================== ManualOverrideStore
def test_override_set_and_get(tmp_db: Path) -> None:
    """Set + get dovrebbero ritornare lo stesso valore."""
    store = ManualOverrideStore(db_path=tmp_db)
    store.set("price", "AAPL", 200.0, api_value=187.42, note="manual fix")
    ov = store.get("price", "AAPL")
    assert ov is not None
    assert ov.user_value == 200.0
    assert ov.api_value == 187.42
    assert ov.note == "manual fix"
    assert ov.is_active is True


def test_override_get_missing(tmp_db: Path) -> None:
    """get su entita' inesistente ritorna None."""
    store = ManualOverrideStore(db_path=tmp_db)
    assert store.get("price", "INESISTENTE") is None


def test_override_resolve_with_active(tmp_db: Path) -> None:
    """resolve con override attivo ritorna user_value, is_override=True."""
    store = ManualOverrideStore(db_path=tmp_db)
    store.set("price", "AAPL", 200.0, api_value=187.42)
    value, is_override = store.resolve("price", "AAPL", api_value=187.42)
    assert value == 200.0
    assert is_override is True


def test_override_resolve_without_active(tmp_db: Path) -> None:
    """resolve senza override ritorna api_value, is_override=False."""
    store = ManualOverrideStore(db_path=tmp_db)
    value, is_override = store.resolve("price", "MSFT", api_value=420.0)
    assert value == 420.0
    assert is_override is False


def test_override_replace_disables_old(tmp_db: Path) -> None:
    """Set su override esistente disattiva quello vecchio."""
    store = ManualOverrideStore(db_path=tmp_db)
    store.set("price", "AAPL", 200.0)
    store.set("price", "AAPL", 210.0)
    ov = store.get("price", "AAPL")
    assert ov is not None
    assert ov.user_value == 210.0
    # History deve avere 2 record (uno disattivato)
    history = store.history("price", "AAPL")
    assert len(history) == 2
    assert sum(1 for h in history if h.is_active) == 1


def test_override_remove(tmp_db: Path) -> None:
    """remove disattiva l'override (soft-delete)."""
    store = ManualOverrideStore(db_path=tmp_db)
    store.set("price", "AAPL", 200.0)
    store.remove("price", "AAPL")
    assert store.get("price", "AAPL") is None
    # History resta consultabile
    history = store.history("price", "AAPL")
    assert len(history) == 1
    assert not history[0].is_active


def test_override_list_active(tmp_db: Path) -> None:
    """list_active ritorna solo override attivi."""
    store = ManualOverrideStore(db_path=tmp_db)
    store.set("price", "AAPL", 200.0)
    store.set("price", "MSFT", 420.0)
    store.set("pe_ratio", "AAPL", 28.0)
    store.remove("price", "MSFT")  # MSFT disattivato
    active = store.list_active()
    assert len(active) == 2
    keys = {(a.entity_type, a.entity_key) for a in active}
    assert ("price", "AAPL") in keys
    assert ("pe_ratio", "AAPL") in keys


# ===================================================== UserDataStore
def test_userdata_upsert_and_get(tmp_db: Path) -> None:
    """upsert + get ritorna lo stesso payload."""
    store = UserDataStore(db_path=tmp_db)
    payload = {"name": "Casa", "target": 80_000, "currency": "EUR"}
    store.upsert("goal", "g1", payload)
    rec = store.get("goal", "g1")
    assert rec is not None
    assert rec.payload["name"] == "Casa"
    assert rec.payload["target"] == 80_000


def test_userdata_upsert_replaces(tmp_db: Path) -> None:
    """upsert su id esistente sostituisce il payload."""
    store = UserDataStore(db_path=tmp_db)
    store.upsert("goal", "g1", {"name": "Casa", "target": 80_000})
    store.upsert("goal", "g1", {"name": "Casa Milano", "target": 100_000})
    rec = store.get("goal", "g1")
    assert rec is not None
    assert rec.payload["name"] == "Casa Milano"
    assert rec.payload["target"] == 100_000


def test_userdata_list_by_type(tmp_db: Path) -> None:
    """list_by_type ritorna tutti i record di un tipo."""
    store = UserDataStore(db_path=tmp_db)
    store.upsert("goal", "g1", {"name": "Casa"})
    store.upsert("goal", "g2", {"name": "Auto"})
    store.upsert("position", "p1", {"ticker": "AAPL"})
    goals = store.list_by_type("goal")
    assert len(goals) == 2
    positions = store.list_by_type("position")
    assert len(positions) == 1


def test_userdata_delete(tmp_db: Path) -> None:
    """delete cancella un record."""
    store = UserDataStore(db_path=tmp_db)
    store.upsert("goal", "g1", {"name": "Casa"})
    assert store.delete("goal", "g1") is True
    assert store.get("goal", "g1") is None
    # Delete su id inesistente -> False
    assert store.delete("goal", "nonexistent") is False


def test_userdata_count(tmp_db: Path) -> None:
    """count ritorna il numero di record di un tipo."""
    store = UserDataStore(db_path=tmp_db)
    assert store.count("goal") == 0
    store.upsert("goal", "g1", {"name": "x"})
    store.upsert("goal", "g2", {"name": "y"})
    assert store.count("goal") == 2


def test_userdata_delete_all_of_type(tmp_db: Path) -> None:
    """delete_all_of_type rimuove tutti i record di un tipo."""
    store = UserDataStore(db_path=tmp_db)
    store.upsert("goal", "g1", {"name": "x"})
    store.upsert("goal", "g2", {"name": "y"})
    store.upsert("position", "p1", {"ticker": "AAPL"})
    n = store.delete_all_of_type("goal")
    assert n == 2
    assert store.count("goal") == 0
    assert store.count("position") == 1


def test_userdata_handles_dates_in_payload(tmp_db: Path) -> None:
    """date e datetime nel payload vengono serializzati come stringhe."""
    store = UserDataStore(db_path=tmp_db)
    payload = {
        "open_date": date(2025, 6, 1),
        "updated_at": datetime(2025, 6, 15, 12, 0, 0),
    }
    store.upsert("position", "p1", payload)
    rec = store.get("position", "p1")
    assert rec is not None
    # date -> string ISO
    assert rec.payload["open_date"] == "2025-06-01"


def test_new_id_unique() -> None:
    """new_id genera id unici."""
    ids = {new_id() for _ in range(100)}
    assert len(ids) == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
