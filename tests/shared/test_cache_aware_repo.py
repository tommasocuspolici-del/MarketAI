"""Tests for shared.db.cache_aware_repo — CacheAwareRepository ABC."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from shared.db.cache_aware_repo import CacheAwareRepository


# ── Concrete test subclass ────────────────────────────────────────────────────

class _FakeRepo(CacheAwareRepository[dict]):
    """Minimal concrete implementation for testing the base class."""

    def __init__(self, duckdb: Any, ttl_seconds: int = 3600) -> None:
        super().__init__(duckdb, ttl_key="test_key", ttl_seconds=ttl_seconds)
        self._store: dict[str, dict] = {}
        self._source_value: dict | None = None

    def _read_from_db(self, key: str) -> dict | None:
        return self._store.get(key)

    def _fetch_from_source(self, key: str) -> dict | None:
        return self._source_value

    def _write_to_db(self, key: str, value: dict) -> None:
        self._store[key] = {**value, "fetched_at": datetime.now(UTC)}

    def _extract_value(self, row: dict) -> dict:
        return {k: v for k, v in row.items() if k != "fetched_at"}


def _fresh_row(offset_seconds: int = 0) -> dict:
    """Row with fetched_at = now - offset_seconds."""
    return {"value": 42, "fetched_at": datetime.now(UTC) - timedelta(seconds=offset_seconds)}


def _stale_row(ttl: int = 3600) -> dict:
    """Row with fetched_at older than TTL."""
    return {"value": 99, "fetched_at": datetime.now(UTC) - timedelta(seconds=ttl + 100)}


# ── Constructor ───────────────────────────────────────────────────────────────

class TestInit:
    def test_ttl_from_seconds(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=900)
        assert repo.ttl_seconds == 900.0

    def test_default_ttl(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=1800)
        assert repo.ttl_seconds == 1800.0


# ── read() ────────────────────────────────────────────────────────────────────

class TestRead:
    def test_cache_hit_returns_value(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        repo._store["spy"] = _fresh_row()
        repo._source_value = {"value": 0}  # should NOT be called
        result = repo.read("spy")
        assert result is not None
        assert result["value"] == 42

    def test_cache_miss_fetches_from_source(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        repo._source_value = {"value": 77}
        result = repo.read("spy")
        assert result is not None
        assert result["value"] == 77

    def test_stale_cache_refetches(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        repo._store["spy"] = _stale_row()
        repo._source_value = {"value": 55}
        result = repo.read("spy")
        assert result is not None
        assert result["value"] == 55

    def test_force_refresh_bypasses_fresh_cache(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        repo._store["spy"] = _fresh_row()
        repo._source_value = {"value": 200}
        result = repo.read("spy", force_refresh=True)
        assert result is not None
        assert result["value"] == 200

    def test_source_failure_returns_none(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        repo._source_value = None
        result = repo.read("spy")
        assert result is None

    def test_write_to_db_called_after_fetch(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        repo._source_value = {"value": 10}
        repo.read("spy")
        assert "spy" in repo._store

    def test_cache_hit_does_not_write_to_db(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        repo._store["spy"] = _fresh_row()
        fetched_at_before = repo._store["spy"]["fetched_at"]
        repo.read("spy")
        assert repo._store["spy"]["fetched_at"] == fetched_at_before


# ── read_or_stale() ───────────────────────────────────────────────────────────

class TestReadOrStale:
    def test_fresh_cache_returned(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        repo._store["spy"] = _fresh_row()
        result = repo.read_or_stale("spy")
        assert result is not None
        assert result["value"] == 42

    def test_stale_cache_with_fresh_fetch(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        repo._store["spy"] = _stale_row()
        repo._source_value = {"value": 88}
        result = repo.read_or_stale("spy")
        assert result["value"] == 88

    def test_stale_cache_fallback_when_fetch_fails(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        repo._store["spy"] = _stale_row()
        repo._source_value = None  # fetch fails
        result = repo.read_or_stale("spy")
        # Should fall back to stale data
        assert result is not None
        assert result["value"] == 99

    def test_no_cache_no_source_returns_none(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        repo._source_value = None
        result = repo.read_or_stale("spy")
        assert result is None


# ── invalidate() ─────────────────────────────────────────────────────────────

class TestInvalidate:
    def test_invalidate_calls_invalidate_in_db(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        called_with: list[str] = []

        def _fake_invalidate(key: str) -> None:
            called_with.append(key)

        repo._invalidate_in_db = _fake_invalidate  # type: ignore[method-assign]
        repo.invalidate("spy")
        assert called_with == ["spy"]

    def test_invalidate_in_db_default_noop(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        repo._invalidate_in_db("spy")  # should not raise


# ── _is_fresh() ───────────────────────────────────────────────────────────────

class TestIsFresh:
    def test_fresh_datetime_utc(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        row = {"fetched_at": datetime.now(UTC) - timedelta(seconds=100)}
        assert repo._is_fresh(row) is True

    def test_stale_datetime(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        row = {"fetched_at": datetime.now(UTC) - timedelta(seconds=4000)}
        assert repo._is_fresh(row) is False

    def test_none_fetched_at_returns_false(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        assert repo._is_fresh({"fetched_at": None}) is False

    def test_missing_fetched_at_returns_false(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        assert repo._is_fresh({}) is False

    def test_string_iso_date(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        recent = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
        assert repo._is_fresh({"fetched_at": recent}) is True

    def test_invalid_string_returns_false(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        assert repo._is_fresh({"fetched_at": "not-a-date"}) is False

    def test_naive_datetime_treated_as_utc(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        naive = datetime.utcnow() - timedelta(seconds=100)  # noqa: DTZ003
        assert repo._is_fresh({"fetched_at": naive}) is True

    def test_uses_computed_at_fallback(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        row = {"computed_at": datetime.now(UTC) - timedelta(seconds=10)}
        assert repo._is_fresh(row) is True

    def test_uses_updated_at_fallback(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        row = {"updated_at": datetime.now(UTC) - timedelta(seconds=10)}
        assert repo._is_fresh(row) is True


# ── _ttl_remaining() ─────────────────────────────────────────────────────────

class TestTtlRemaining:
    def test_fresh_row_has_positive_remaining(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        row = {"fetched_at": datetime.now(UTC) - timedelta(seconds=100)}
        assert repo._ttl_remaining(row) > 0

    def test_stale_row_returns_zero(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        row = {"fetched_at": datetime.now(UTC) - timedelta(seconds=4000)}
        assert repo._ttl_remaining(row) == 0.0

    def test_none_fetched_at_returns_zero(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        assert repo._ttl_remaining({"fetched_at": None}) == 0.0

    def test_missing_key_returns_zero(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        assert repo._ttl_remaining({}) == 0.0

    def test_string_iso_date(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        recent = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
        remaining = repo._ttl_remaining({"fetched_at": recent})
        assert remaining > 0

    def test_invalid_string_returns_zero(self) -> None:
        repo = _FakeRepo(MagicMock(), ttl_seconds=3600)
        assert repo._ttl_remaining({"fetched_at": "bad-date"}) == 0.0
