"""Tests for custom_indicators.registry — CustomIndicatorRegistry."""
from __future__ import annotations

from pathlib import Path

import pytest

from custom_indicators.registry import CustomIndicatorRegistry, IndicatorDefinition


class TestRegistryLoadFromYaml:
    def test_loads_from_project_yaml(self) -> None:
        reg = CustomIndicatorRegistry()
        count = reg.load_from_yaml()
        assert count >= 10    # DoD: 10 indicators loaded without error

    def test_all_required_ids_present(self) -> None:
        reg = CustomIndicatorRegistry()
        reg.load_from_yaml()
        ids = {d.id for d in reg.list_all()}
        expected = {
            "personal_risk_budget", "portfolio_momentum", "macro_alignment_score",
            "entry_window", "stress_exposure", "liquidity_reserve",
            "signal_confidence_tracker", "regime_signal_filter",
            "consensus_signal_validator", "volatility_adjusted_signal",
        }
        assert expected.issubset(ids)

    def test_missing_yaml_returns_zero(self) -> None:
        reg = CustomIndicatorRegistry()
        count = reg.load_from_yaml(Path("/nonexistent/path.yaml"))
        assert count == 0

    def test_active_indicators_subset_of_all(self) -> None:
        reg = CustomIndicatorRegistry()
        reg.load_from_yaml()
        assert len(reg.list_active()) <= len(reg.list_all())


class TestRegistryCRUD:
    def test_register_and_get(self) -> None:
        reg = CustomIndicatorRegistry()
        defn = IndicatorDefinition(id="test_x", name="Test X")
        reg.register(defn)
        assert reg.get("test_x") is not None
        assert reg.get("test_x").name == "Test X"

    def test_get_unknown_returns_none(self) -> None:
        reg = CustomIndicatorRegistry()
        assert reg.get("nonexistent") is None

    def test_deactivate(self) -> None:
        reg = CustomIndicatorRegistry()
        reg.register(IndicatorDefinition(id="x", name="X", active=True))
        assert reg.deactivate("x") is True
        assert reg.get("x").active is False

    def test_deactivate_nonexistent_returns_false(self) -> None:
        reg = CustomIndicatorRegistry()
        assert reg.deactivate("ghost") is False

    def test_remove(self) -> None:
        reg = CustomIndicatorRegistry()
        reg.register(IndicatorDefinition(id="y", name="Y"))
        assert reg.remove("y") is True
        assert reg.get("y") is None

    def test_remove_nonexistent_returns_false(self) -> None:
        reg = CustomIndicatorRegistry()
        assert reg.remove("ghost") is False

    def test_list_active_filters_inactive(self) -> None:
        reg = CustomIndicatorRegistry()
        reg.register(IndicatorDefinition(id="a", name="A", active=True))
        reg.register(IndicatorDefinition(id="b", name="B", active=False))
        active_ids = {d.id for d in reg.list_active()}
        assert "a" in active_ids
        assert "b" not in active_ids
