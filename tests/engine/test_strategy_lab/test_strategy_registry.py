"""Tests for StrategyRegistry — DoD: activate blocked without validation."""
from __future__ import annotations

import pytest

from engine.strategy_lab.strategy_registry import StrategyRecord, StrategyRegistry


class TestRegisterAndGet:
    def test_register_returns_record(self) -> None:
        reg = StrategyRegistry()
        rec = reg.register("SMA Crossover", description="Simple MA cross")
        assert isinstance(rec, StrategyRecord)
        assert rec.name == "SMA Crossover"

    def test_get_returns_registered_strategy(self) -> None:
        reg = StrategyRegistry()
        rec = reg.register("RSI Momentum")
        found = reg.get(rec.strategy_id)
        assert found is not None
        assert found.name == "RSI Momentum"

    def test_get_unknown_returns_none(self) -> None:
        reg = StrategyRegistry()
        assert reg.get("nonexistent") is None

    def test_custom_strategy_id(self) -> None:
        reg = StrategyRegistry()
        rec = reg.register("My Strategy", strategy_id="my_custom_id")
        assert rec.strategy_id == "my_custom_id"


class TestValidation:
    def test_mark_validated_sets_flag(self) -> None:
        reg = StrategyRegistry()
        rec = reg.register("Test Strategy")
        result = reg.mark_validated(rec.strategy_id, sharpe_oos=0.5, n_folds=4)
        assert result is True
        updated = reg.get(rec.strategy_id)
        assert updated.is_validated is True
        assert updated.sharpe_oos == pytest.approx(0.5)
        assert updated.n_folds == 4

    def test_mark_validated_nonexistent_returns_false(self) -> None:
        reg = StrategyRegistry()
        assert reg.mark_validated("ghost", sharpe_oos=0.5, n_folds=4) is False

    def test_version_incremented_after_validation(self) -> None:
        reg = StrategyRegistry()
        rec = reg.register("V Strategy")
        reg.mark_validated(rec.strategy_id, sharpe_oos=0.4, n_folds=4)
        updated = reg.get(rec.strategy_id)
        assert updated.version == rec.version + 1


class TestActivation:
    def test_activate_requires_validation(self) -> None:
        """DoD: WalkForwardValidator obbligatoria prima di is_active=True."""
        reg = StrategyRegistry()
        rec = reg.register("Not Validated")
        with pytest.raises(ValueError, match="walk-forward validation"):
            reg.activate(rec.strategy_id)
        # Verify still not active
        assert reg.get(rec.strategy_id).is_active is False

    def test_activate_after_validation_succeeds(self) -> None:
        reg = StrategyRegistry()
        rec = reg.register("Validated Strategy")
        reg.mark_validated(rec.strategy_id, sharpe_oos=0.4, n_folds=4)
        assert reg.activate(rec.strategy_id) is True
        assert reg.get(rec.strategy_id).is_active is True

    def test_activate_nonexistent_returns_false(self) -> None:
        reg = StrategyRegistry()
        assert reg.activate("ghost") is False

    def test_deactivate(self) -> None:
        reg = StrategyRegistry()
        rec = reg.register("To Deactivate")
        reg.mark_validated(rec.strategy_id, sharpe_oos=0.5, n_folds=4)
        reg.activate(rec.strategy_id)
        assert reg.deactivate(rec.strategy_id) is True
        assert reg.get(rec.strategy_id).is_active is False


class TestListing:
    def test_list_all_returns_all(self) -> None:
        reg = StrategyRegistry()
        reg.register("A")
        reg.register("B")
        assert len(reg.list_all()) >= 2

    def test_list_active_filters_inactive(self) -> None:
        reg = StrategyRegistry()
        ra = reg.register("Active")
        ri = reg.register("Inactive")
        reg.mark_validated(ra.strategy_id, sharpe_oos=0.5, n_folds=4)
        reg.activate(ra.strategy_id)
        active_ids = {r.strategy_id for r in reg.list_active()}
        assert ra.strategy_id in active_ids
        assert ri.strategy_id not in active_ids


class TestRemove:
    def test_remove_existing(self) -> None:
        reg = StrategyRegistry()
        rec = reg.register("To Remove")
        assert reg.remove(rec.strategy_id) is True
        assert reg.get(rec.strategy_id) is None

    def test_remove_nonexistent(self) -> None:
        reg = StrategyRegistry()
        assert reg.remove("ghost") is False
