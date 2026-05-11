"""Tests for shared.health."""
from __future__ import annotations

from shared.health import ComponentHealth, HealthChecker
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
