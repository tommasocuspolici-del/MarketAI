"""Tests for engine.backtesting.strategy (ABC + StrategySignal contract)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.backtesting.strategy import Strategy, StrategySignal
from shared.exceptions import BacktestError


def _ohlcv(n: int = 50) -> pd.DataFrame:
    """Trivial OHLCV DataFrame for contract tests."""
    rng = np.random.default_rng(seed=1)
    ts = pd.date_range(start="2025-01-01", periods=n, freq="D", tz="UTC")
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, size=n)))
    return pd.DataFrame(
        {
            "ts": ts, "open": close, "high": close * 1.01, "low": close * 0.99,
            "close": close, "volume": [1000] * n,
        }
    )


class _DummyStrategy(Strategy):
    """Fake strategy that emits constant positions for contract tests."""

    def __init__(self, value: float = 0.5) -> None:
        self._value = value

    @property
    def name(self) -> str:
        return f"Dummy_{self._value}"

    def generate_signals(self, ohlcv: pd.DataFrame) -> StrategySignal:
        close = self._ensure_close(ohlcv)
        positions = pd.Series([self._value] * len(close), index=close.index, dtype="float64")
        return StrategySignal(
            positions=positions, name=self.name, params={"value": self._value}
        )


class TestStrategySignal:
    def test_valid_positions_accepted(self) -> None:
        ohlcv = _ohlcv(10)
        sig = _DummyStrategy(value=0.5).generate_signals(ohlcv)
        assert len(sig.positions) == 10
        assert sig.params["value"] == 0.5

    def test_out_of_range_positions_rejected(self) -> None:
        # Posizione 1.5 > 1.0 → BacktestError dal __post_init__
        positions = pd.Series([1.5, 0.5, 0.0])
        with pytest.raises(BacktestError, match="out of"):
            StrategySignal(positions=positions, name="bad", params={})

    def test_empty_positions_no_error(self) -> None:
        positions = pd.Series([], dtype="float64")
        sig = StrategySignal(positions=positions, name="empty", params={})
        assert len(sig.positions) == 0


class TestStrategyAbstract:
    def test_cannot_instantiate_abstract(self) -> None:
        with pytest.raises(TypeError):
            Strategy()  # type: ignore[abstract]

    def test_concrete_subclass_works(self) -> None:
        # _DummyStrategy implementa name + generate_signals → istanziabile
        strategy = _DummyStrategy()
        ohlcv = _ohlcv(5)
        sig = strategy.generate_signals(ohlcv)
        assert sig.name == "Dummy_0.5"

    def test_ensure_close_rejects_missing_column(self) -> None:
        bad = pd.DataFrame({"ts": pd.date_range("2025-01-01", periods=3, tz="UTC")})
        strategy = _DummyStrategy()
        with pytest.raises(BacktestError, match="close"):
            strategy.generate_signals(bad)

    def test_ensure_close_rejects_empty(self) -> None:
        empty = pd.DataFrame({"ts": [], "close": []})
        strategy = _DummyStrategy()
        with pytest.raises(BacktestError, match="empty"):
            strategy.generate_signals(empty)
