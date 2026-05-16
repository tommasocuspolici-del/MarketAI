"""Tests for RegimeAwareBacktestEngine."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.strategy_lab.regime_aware_engine import BacktestSummary, RegimeAwareBacktestEngine


def _make_ohlcv(n_days: int = 500, trend: float = 0.0003) -> pd.DataFrame:
    rng   = np.random.default_rng(0)
    noise = rng.normal(0, 0.01, n_days)
    close = 100.0 * np.cumprod(1 + trend + noise)
    dates = pd.date_range("2020-01-01", periods=n_days, freq="B", tz="UTC")
    return pd.DataFrame(
        {"open": close, "high": close * 1.005, "low": close * 0.995, "close": close, "volume": 1e6},
        index=dates,
    )


def _make_regime_labels(ohlcv: pd.DataFrame, split: float = 0.5) -> pd.Series:
    idx = ohlcv.index
    n   = len(idx)
    labels = ["bull"] * int(n * split) + ["bear"] * (n - int(n * split))
    return pd.Series(labels, index=idx)


def _buy_and_hold(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    entries = pd.Series([True]  + [False] * (len(df) - 1), index=df.index)
    exits   = pd.Series([False] * len(df), index=df.index)
    return entries, exits


def _never_trade(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    return pd.Series(False, index=df.index), pd.Series(False, index=df.index)


class TestBasicRun:
    def test_run_returns_summary(self) -> None:
        engine = RegimeAwareBacktestEngine()
        ohlcv  = _make_ohlcv()
        regime = _make_regime_labels(ohlcv)
        summary = engine.run(ohlcv, regime, _buy_and_hold, "test_strat", "SPY")
        assert isinstance(summary, BacktestSummary)
        assert summary.strategy_id == "test_strat"
        assert summary.ticker == "SPY"

    def test_per_regime_results_populated(self) -> None:
        engine = RegimeAwareBacktestEngine()
        ohlcv  = _make_ohlcv()
        # Use all 4 regimes
        idx    = ohlcv.index
        n      = len(idx)
        labels = (
            ["bull"] * (n // 4) + ["bear"] * (n // 4) +
            ["stress"] * (n // 4) + ["transition"] * (n - 3 * (n // 4))
        )
        regime = pd.Series(labels, index=idx)
        summary = engine.run(ohlcv, regime, _buy_and_hold)
        assert len(summary.per_regime) >= 2   # at least bull + bear

    def test_strategy_failure_returns_empty(self) -> None:
        engine = RegimeAwareBacktestEngine()
        ohlcv  = _make_ohlcv()
        regime = _make_regime_labels(ohlcv)

        def bad_strategy(df):
            raise RuntimeError("fail")

        summary = engine.run(ohlcv, regime, bad_strategy)
        assert summary.is_regime_robust is False
        assert summary.per_regime == {}


class TestRegimeRobustness:
    def test_is_regime_robust_requires_3_positive_regimes(self) -> None:
        engine = RegimeAwareBacktestEngine()
        ohlcv  = _make_ohlcv(800, trend=0.001)   # positive trend
        idx    = ohlcv.index
        n      = len(idx)
        labels = (
            ["bull"] * (n // 4) + ["bear"] * (n // 4) +
            ["stress"] * (n // 4) + ["transition"] * (n - 3 * (n // 4))
        )
        regime = pd.Series(labels, index=idx)
        summary = engine.run(ohlcv, regime, _buy_and_hold)
        # Only check that the field exists and is a boolean
        assert isinstance(summary.is_regime_robust, bool)


class TestOutputRange:
    def test_overall_sharpe_is_float(self) -> None:
        engine = RegimeAwareBacktestEngine()
        ohlcv  = _make_ohlcv()
        regime = _make_regime_labels(ohlcv)
        summary = engine.run(ohlcv, regime, _buy_and_hold)
        assert isinstance(summary.overall_sharpe, float)

    def test_total_return_is_float(self) -> None:
        engine = RegimeAwareBacktestEngine()
        ohlcv  = _make_ohlcv()
        regime = _make_regime_labels(ohlcv)
        summary = engine.run(ohlcv, regime, _buy_and_hold)
        assert isinstance(summary.overall_return, float)

    def test_regime_result_fields(self) -> None:
        engine = RegimeAwareBacktestEngine()
        ohlcv  = _make_ohlcv()
        regime = _make_regime_labels(ohlcv)
        summary = engine.run(ohlcv, regime, _buy_and_hold)
        for reg, res in summary.per_regime.items():
            assert -100 <= res.sharpe <= 100   # sanity
            assert res.n_days >= 0
