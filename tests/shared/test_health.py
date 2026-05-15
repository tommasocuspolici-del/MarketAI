"""Tests for shared.health."""
from __future__ import annotations

from shared.health import (
    ComponentHealth,
    HealthChecker,
    SystemHealth,
    cache_probe_factory,
    duckdb_probe_factory,
    scheduler_probe_factory,
    sqlite_probe_factory,
)
from shared.types import HealthState


def _make_probe(name: str, state: HealthState, message: str | None = None):
    def _probe() -> ComponentHealth:
        return ComponentHealth(name=name, status=state, message=message)

    return _probe


class TestHealthChecker:
    def test_no_probes_returns_operational(self) -> None:
        checker = HealthChecker()
        result = checker.check_all()
        # Solo error_budget probe built-in presente
        assert result.status == HealthState.OPERATIONAL

    def test_all_operational_components(self) -> None:
        checker = HealthChecker()
        checker.register_probe("a", _make_probe("a", HealthState.OPERATIONAL))
        checker.register_probe("b", _make_probe("b", HealthState.OPERATIONAL))
        result = checker.check_all()
        assert result.status == HealthState.OPERATIONAL
        assert result.is_operational

    def test_degraded_aggregation(self) -> None:
        checker = HealthChecker()
        checker.register_probe("a", _make_probe("a", HealthState.OPERATIONAL))
        checker.register_probe("b", _make_probe("b", HealthState.DEGRADED))
        result = checker.check_all()
        assert result.status == HealthState.DEGRADED

    def test_down_beats_degraded(self) -> None:
        checker = HealthChecker()
        checker.register_probe("a", _make_probe("a", HealthState.DEGRADED))
        checker.register_probe("b", _make_probe("b", HealthState.DOWN))
        result = checker.check_all()
        assert result.status == HealthState.DOWN

    def test_raising_probe_becomes_down(self) -> None:
        checker = HealthChecker()

        def _bad_probe() -> ComponentHealth:
            raise RuntimeError("boom")

        checker.register_probe("bad", _bad_probe)
        result = checker.check_all()
        assert result.status == HealthState.DOWN
        bad_comp = next(c for c in result.components if c.name == "bad")
        assert bad_comp.status == HealthState.DOWN
        assert "boom" in (bad_comp.message or "")

    def test_to_dict_serializable(self) -> None:
        checker = HealthChecker()
        checker.register_probe("a", _make_probe("a", HealthState.OPERATIONAL))
        result = checker.check_all()
        d = result.to_dict()
        assert "status" in d
        assert "components" in d
        assert isinstance(d["components"], list)

    def test_register_probe_replaces_existing(self) -> None:
        checker = HealthChecker()
        checker.register_probe("a", _make_probe("a", HealthState.OPERATIONAL))
        checker.register_probe("a", _make_probe("a", HealthState.DEGRADED))
        result = checker.check_all()
        comp_a = next(c for c in result.components if c.name == "a")
        assert comp_a.status == HealthState.DEGRADED

    def test_system_health_is_not_operational_when_down(self) -> None:
        checker = HealthChecker()
        checker.register_probe("x", _make_probe("x", HealthState.DOWN))
        result = checker.check_all()
        assert not result.is_operational

    def test_component_health_to_dict(self) -> None:
        comp = ComponentHealth(name="db", status=HealthState.OPERATIONAL, latency_ms=5.0)
        d = comp.to_dict()
        assert d["name"] == "db"
        assert d["status"] == "operational"
        assert d["latency_ms"] == 5.0


class TestDuckdbProbeFactory:
    def test_ok_when_query_succeeds(self) -> None:
        probe = duckdb_probe_factory(lambda sql: None)
        result = probe()
        assert result.status == HealthState.OPERATIONAL
        assert result.name == "duckdb"
        assert result.latency_ms is not None

    def test_down_when_query_raises(self) -> None:
        def _bad(sql: str) -> None:
            raise RuntimeError("connection refused")

        probe = duckdb_probe_factory(_bad)
        result = probe()
        assert result.status == HealthState.DOWN
        assert "connection refused" in (result.message or "")


class TestSqliteProbeFactory:
    def test_ok_when_query_succeeds(self) -> None:
        probe = sqlite_probe_factory(lambda sql: None)
        result = probe()
        assert result.status == HealthState.OPERATIONAL
        assert result.name == "sqlite"

    def test_down_when_query_raises(self) -> None:
        def _bad(sql: str) -> None:
            raise RuntimeError("sqlite error")

        probe = sqlite_probe_factory(_bad)
        result = probe()
        assert result.status == HealthState.DOWN


class TestCacheProbeFactory:
    def test_ok_when_round_trip_succeeds(self) -> None:
        store: dict[str, str] = {}

        def _set(k: str, v: str, ttl: int) -> None:
            store[k] = v

        def _get(k: str) -> str:
            return store.get(k, "")

        probe = cache_probe_factory(_set, _get)
        result = probe()
        assert result.status == HealthState.OPERATIONAL
        assert result.name == "cache"

    def test_down_when_read_returns_wrong_value(self) -> None:
        def _set(k: str, v: str, ttl: int) -> None:
            pass

        def _get(k: str) -> str:
            return "wrong"

        probe = cache_probe_factory(_set, _get)
        result = probe()
        assert result.status == HealthState.DOWN

    def test_down_when_set_raises(self) -> None:
        def _set(k: str, v: str, ttl: int) -> None:
            raise RuntimeError("cache unavailable")

        def _get(k: str) -> None:
            return None

        probe = cache_probe_factory(_set, _get)
        result = probe()
        assert result.status == HealthState.DOWN


class TestSchedulerProbeFactory:
    def test_operational_when_running(self) -> None:
        probe = scheduler_probe_factory(lambda: True)
        result = probe()
        assert result.status == HealthState.OPERATIONAL
        assert result.name == "scheduler"

    def test_degraded_when_not_running(self) -> None:
        probe = scheduler_probe_factory(lambda: False)
        result = probe()
        assert result.status == HealthState.DEGRADED
        assert "not running" in (result.message or "")

    def test_down_when_fn_raises(self) -> None:
        def _boom() -> bool:
            raise RuntimeError("scheduler crashed")

        probe = scheduler_probe_factory(_boom)
        result = probe()
        assert result.status == HealthState.DOWN
        assert "scheduler crashed" in (result.message or "")
