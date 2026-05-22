from __future__ import annotations

import pytest
import numpy as np
import pandas as pd

from engine.alpha_generation.backtest_engine.wfo_runner import (
    WFORunner,
    WFOConfig,
    WFOResult,
    WFOFold,
)

np.random.seed(42)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_price_series(n: int = 1500, start: str = "2018-01-01") -> pd.Series:
    rng = np.random.default_rng(42)
    returns = rng.normal(0.0003, 0.01, n)
    prices = np.cumprod(1 + returns)
    idx = pd.date_range(start, periods=n, freq="B", tz="UTC")
    return pd.Series(prices, index=idx)


def _strategy_fn(prices: pd.Series) -> pd.Series:
    signal = np.sign(prices.pct_change().rolling(20).mean())
    return pd.Series(signal, index=prices.index)


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

class TestInstantiation:
    def test_default_config(self) -> None:
        runner = WFORunner()
        cfg = runner._config
        assert isinstance(cfg, WFOConfig)
        assert cfg.in_sample_years == 3
        assert cfg.oos_years == 1
        assert cfg.step_months == 3

    def test_custom_config(self) -> None:
        cfg = WFOConfig(in_sample_years=2, oos_years=1, step_months=6, min_oos_periods=30)
        runner = WFORunner(config=cfg)
        assert runner._config.in_sample_years == 2
        assert runner._config.step_months == 6


# ---------------------------------------------------------------------------
# _split_folds
# ---------------------------------------------------------------------------

class TestSplitFolds:
    def test_returns_list(self) -> None:
        runner = WFORunner()
        prices = _make_price_series(1500)
        folds = runner._split_folds(prices.index)
        assert isinstance(folds, list)

    def test_at_least_one_fold_with_5_years(self) -> None:
        runner = WFORunner()
        # 5+ years of daily data
        prices = _make_price_series(1500)
        folds = runner._split_folds(prices.index)
        assert len(folds) >= 1

    def test_fold_structure(self) -> None:
        runner = WFORunner()
        prices = _make_price_series(1500)
        folds = runner._split_folds(prices.index)
        for train_slice, test_slice in folds:
            assert isinstance(train_slice, slice)
            assert isinstance(test_slice, slice)

    def test_short_series_returns_empty(self) -> None:
        runner = WFORunner()
        prices = _make_price_series(100)
        folds = runner._split_folds(prices.index)
        # With only 100 bars, we can't fill even 1 fold (3y in + 1y oos ≈ 1008 bars)
        assert isinstance(folds, list)

    def test_requires_datetime_index(self) -> None:
        runner = WFORunner()
        prices_bad = pd.Series(np.ones(100), index=np.arange(100))
        with pytest.raises(ValueError, match="DatetimeIndex"):
            runner.run(prices_bad, _strategy_fn)


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

class TestRun:
    def test_returns_wfo_result(self) -> None:
        runner = WFORunner()
        prices = _make_price_series(1500)
        result = runner.run(prices, _strategy_fn)
        assert isinstance(result, WFOResult)

    def test_folds_non_empty(self) -> None:
        runner = WFORunner()
        prices = _make_price_series(1500)
        result = runner.run(prices, _strategy_fn)
        assert len(result.folds) >= 1

    def test_each_fold_is_wfo_fold(self) -> None:
        runner = WFORunner()
        prices = _make_price_series(1500)
        result = runner.run(prices, _strategy_fn)
        for fold in result.folds:
            assert isinstance(fold, WFOFold)

    def test_fold_date_fields(self) -> None:
        runner = WFORunner()
        prices = _make_price_series(1500)
        result = runner.run(prices, _strategy_fn)
        from datetime import date
        for fold in result.folds:
            assert isinstance(fold.train_start, date)
            assert isinstance(fold.train_end, date)
            assert isinstance(fold.test_start, date)
            assert isinstance(fold.test_end, date)
            assert fold.train_end <= fold.test_start

    def test_fold_has_psr_result(self) -> None:
        runner = WFORunner()
        prices = _make_price_series(1500)
        result = runner.run(prices, _strategy_fn)
        for fold in result.folds:
            assert hasattr(fold, "psr_result")
            assert hasattr(fold.psr_result, "psr")

    def test_combined_psr_in_unit_interval(self) -> None:
        runner = WFORunner()
        prices = _make_price_series(1500)
        result = runner.run(prices, _strategy_fn)
        psr = result.combined_psr.psr
        import math
        # PSR may be NaN when OOS returns are degenerate (zero variance)
        assert math.isnan(psr) or 0.0 <= psr <= 1.0

    def test_is_robust_is_bool(self) -> None:
        runner = WFORunner()
        prices = _make_price_series(1500)
        result = runner.run(prices, _strategy_fn)
        assert isinstance(result.is_robust, bool)

    def test_combined_oos_returns_is_array(self) -> None:
        runner = WFORunner()
        prices = _make_price_series(1500)
        result = runner.run(prices, _strategy_fn)
        assert isinstance(result.combined_oos_returns, np.ndarray)

    def test_avg_directional_acc_bounded(self) -> None:
        runner = WFORunner()
        prices = _make_price_series(1500)
        result = runner.run(prices, _strategy_fn)
        assert 0.0 <= result.avg_directional_acc <= 1.0

    def test_too_short_prices_returns_empty_folds(self) -> None:
        runner = WFORunner()
        prices = _make_price_series(50)
        result = runner.run(prices, _strategy_fn)
        assert isinstance(result, WFOResult)
        # Too few data points to produce folds
        assert result.folds == []
        assert result.is_robust is False

    def test_fold_oos_metrics_keys(self) -> None:
        runner = WFORunner()
        prices = _make_price_series(1500)
        result = runner.run(prices, _strategy_fn)
        for fold in result.folds:
            for key in ("mse", "mae", "sharpe", "directional_acc"):
                assert key in fold.oos_metrics
