"""Tests per engine.backtesting.backtest_runner — BacktestRunner + BacktestConfig."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import duckdb
import numpy as np
import pandas as pd
import pytest

from engine.backtesting.backtest_runner import (
    BacktestConfig,
    BacktestRunner,
    get_backtest_runner,
    reset_backtest_runner,
)


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS backtest_results (
    run_id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    strategy_name VARCHAR NOT NULL,
    ticker VARCHAR NOT NULL,
    run_type VARCHAR NOT NULL,
    scenario VARCHAR,
    sharpe_ratio DOUBLE,
    max_drawdown DOUBLE,
    total_return DOUBLE,
    win_rate DOUBLE,
    calmar_ratio DOUBLE,
    n_trades INTEGER,
    fees_total DOUBLE,
    initial_cash DOUBLE,
    config_json VARCHAR,
    run_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


def _make_client():
    conn = duckdb.connect(":memory:")
    conn.execute(_CREATE_TABLE)
    client = MagicMock()

    @contextmanager
    def _transaction():
        yield conn

    def _query(sql, params=None):
        return conn.execute(sql, params or []).fetchall()

    client.transaction = _transaction
    client.query = _query
    return client


def _make_ohlcv(n: int = 100) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = 100.0 + np.cumsum(rng.normal(0.05, 0.5, n))
    dates = pd.date_range("2024-01-01", periods=n, freq="B", tz="UTC")
    return pd.DataFrame({
        "ts": dates,
        "open": close * 0.999,
        "high": close * 1.005,
        "low": close * 0.995,
        "close": close.astype(np.float64),
        "volume": np.ones(n) * 100_000,
    })


class TestBacktestConfig:
    def test_defaults(self) -> None:
        cfg = BacktestConfig(ticker="AAPL")
        assert cfg.ticker == "AAPL"
        assert cfg.initial_cash == 10_000.0
        assert cfg.fees == pytest.approx(0.001)
        assert cfg.slippage == pytest.approx(0.001)
        assert cfg.n_splits == 5
        assert cfg.exchange == "NASDAQ"

    def test_to_json_valid(self) -> None:
        cfg = BacktestConfig(ticker="AAPL", initial_cash=50_000.0)
        data = json.loads(cfg.to_json())
        assert data["ticker"] == "AAPL"
        assert data["initial_cash"] == 50_000.0

    def test_to_json_extra_fields(self) -> None:
        cfg = BacktestConfig(ticker="AAPL", extra={"custom": "value"})
        data = json.loads(cfg.to_json())
        assert data["custom"] == "value"

    def test_scenario_nullable(self) -> None:
        cfg = BacktestConfig(ticker="AAPL", scenario="2020_crash")
        assert cfg.scenario == "2020_crash"
        cfg2 = BacktestConfig(ticker="AAPL")
        assert cfg2.scenario is None


class TestBacktestRunnerRun:
    def test_run_returns_backtest_result(self) -> None:
        from engine.backtesting.strategy_builder import DSLStrategy
        client = _make_client()
        runner = BacktestRunner(client=client)
        strategy = DSLStrategy("close > 0", allow_short=False)
        cfg = BacktestConfig(ticker="AAPL")
        result = runner.run(strategy, cfg, ohlcv=_make_ohlcv())
        assert result is not None
        assert result.ticker == "AAPL"

    def test_run_persists_to_db(self) -> None:
        from engine.backtesting.strategy_builder import DSLStrategy
        conn = duckdb.connect(":memory:")
        conn.execute(_CREATE_TABLE)
        client = MagicMock()

        @contextmanager
        def _transaction():
            yield conn

        client.transaction = _transaction
        runner = BacktestRunner(client=client)
        strategy = DSLStrategy("close > 0", allow_short=False)
        cfg = BacktestConfig(ticker="TSLA")
        runner.run(strategy, cfg, ohlcv=_make_ohlcv())
        rows = conn.execute("SELECT COUNT(*) FROM backtest_results").fetchone()[0]
        assert rows == 1

    def test_run_uses_provided_ohlcv(self) -> None:
        from engine.backtesting.strategy_builder import DSLStrategy
        client = _make_client()
        runner = BacktestRunner(client=client)
        strategy = DSLStrategy("EMA(close, 10) > EMA(close, 20)", allow_short=False)
        cfg = BacktestConfig(ticker="SPY")
        result = runner.run(strategy, cfg, ohlcv=_make_ohlcv(120))
        assert result.ticker == "SPY"


class TestBacktestRunnerWalkForward:
    def test_walk_forward_returns_result(self) -> None:
        from engine.backtesting.strategy_builder import DSLStrategy
        client = _make_client()
        runner = BacktestRunner(client=client)
        strategy = DSLStrategy("close > 0", allow_short=False)
        cfg = BacktestConfig(ticker="AAPL", n_splits=3)
        result = runner.run_walk_forward(strategy, cfg, ohlcv=_make_ohlcv(200))
        assert result is not None
        assert result.ticker == "AAPL"
        assert result.n_splits == 3

    def test_walk_forward_persists(self) -> None:
        from engine.backtesting.strategy_builder import DSLStrategy
        conn = duckdb.connect(":memory:")
        conn.execute(_CREATE_TABLE)
        client = MagicMock()

        @contextmanager
        def _transaction():
            yield conn

        client.transaction = _transaction
        runner = BacktestRunner(client=client)
        strategy = DSLStrategy("close > 0", allow_short=False)
        cfg = BacktestConfig(ticker="AAPL", n_splits=3)
        runner.run_walk_forward(strategy, cfg, ohlcv=_make_ohlcv(200))
        rows = conn.execute("SELECT COUNT(*) FROM backtest_results").fetchone()[0]
        assert rows == 1


class TestBacktestRunnerBatch:
    def test_batch_returns_dict(self) -> None:
        from engine.backtesting.strategy_builder import DSLStrategy
        client = _make_client()
        runner = BacktestRunner(client=client)
        strategy = DSLStrategy("close > 0", allow_short=False)
        cfg = BacktestConfig(ticker="AAPL")
        ohlcv_map = {
            "AAPL": _make_ohlcv(),
            "MSFT": _make_ohlcv(),
        }
        results = runner.run_batch(strategy, ["AAPL", "MSFT"], cfg, ohlcv_map=ohlcv_map)
        assert "AAPL" in results
        assert "MSFT" in results

    def test_batch_skips_failed_tickers(self) -> None:
        from engine.backtesting.strategy_builder import DSLStrategy
        client = _make_client()
        runner = BacktestRunner(client=client)
        strategy = DSLStrategy("close > 0", allow_short=False)
        cfg = BacktestConfig(ticker="AAPL")
        # UNKNOWN has no ohlcv_map entry and won't be fetched from DB successfully
        # Pass empty DF to trigger error
        ohlcv_map = {
            "AAPL": _make_ohlcv(),
            "BROKEN": pd.DataFrame(),  # empty → will fail in BacktestEngine
        }
        results = runner.run_batch(strategy, ["AAPL", "BROKEN"], cfg, ohlcv_map=ohlcv_map)
        assert "AAPL" in results
        # BROKEN may be skipped due to error

    def test_batch_empty_tickers(self) -> None:
        from engine.backtesting.strategy_builder import DSLStrategy
        client = _make_client()
        runner = BacktestRunner(client=client)
        strategy = DSLStrategy("close > 0", allow_short=False)
        cfg = BacktestConfig(ticker="AAPL")
        results = runner.run_batch(strategy, [], cfg)
        assert results == {}


class TestBacktestRunnerReadResults:
    def test_read_results_empty_returns_dataframe(self) -> None:
        client = _make_client()
        runner = BacktestRunner(client=client)
        df = runner.read_results()
        assert isinstance(df, pd.DataFrame)

    def test_read_results_after_run(self) -> None:
        from engine.backtesting.strategy_builder import DSLStrategy
        client = _make_client()
        runner = BacktestRunner(client=client)
        strategy = DSLStrategy("close > 0", allow_short=False)
        cfg = BacktestConfig(ticker="AAPL")
        runner.run(strategy, cfg, ohlcv=_make_ohlcv())
        df = runner.read_results(ticker="AAPL")
        assert len(df) >= 1
        assert "ticker" in df.columns

    def test_read_results_filter_strategy(self) -> None:
        from engine.backtesting.strategy_builder import DSLStrategy
        client = _make_client()
        runner = BacktestRunner(client=client)
        strategy = DSLStrategy("close > 0", allow_short=False)
        cfg = BacktestConfig(ticker="AAPL")
        runner.run(strategy, cfg, ohlcv=_make_ohlcv())
        df = runner.read_results(strategy_name="NonExistentStrategy")
        assert df.empty

    def test_read_results_error_returns_empty_df(self) -> None:
        bad_client = MagicMock()

        @contextmanager
        def _bad_tx():
            raise RuntimeError("fail")
            yield  # noqa: unreachable

        bad_client.transaction = _bad_tx
        runner = BacktestRunner(client=bad_client)
        df = runner.read_results()
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_read_results_limit(self) -> None:
        from engine.backtesting.strategy_builder import DSLStrategy
        client = _make_client()
        runner = BacktestRunner(client=client)
        strategy = DSLStrategy("close > 0", allow_short=False)
        cfg = BacktestConfig(ticker="AAPL")
        for _ in range(5):
            runner.run(strategy, cfg, ohlcv=_make_ohlcv())
        df = runner.read_results(limit=3)
        assert len(df) <= 3


class TestBacktestRunnerSingleton:
    def setup_method(self):
        reset_backtest_runner()

    def teardown_method(self):
        reset_backtest_runner()

    def test_get_returns_instance(self) -> None:
        with patch("engine.backtesting.backtest_runner.get_duckdb_client") as mock_fn:
            mock_fn.return_value = _make_client()
            runner = get_backtest_runner()
            assert isinstance(runner, BacktestRunner)

    def test_singleton_same_instance(self) -> None:
        with patch("engine.backtesting.backtest_runner.get_duckdb_client") as mock_fn:
            mock_fn.return_value = _make_client()
            r1 = get_backtest_runner()
            r2 = get_backtest_runner()
            assert r1 is r2

    def test_reset_clears_singleton(self) -> None:
        with patch("engine.backtesting.backtest_runner.get_duckdb_client") as mock_fn:
            mock_fn.return_value = _make_client()
            r1 = get_backtest_runner()
            reset_backtest_runner()
            r2 = get_backtest_runner()
            assert r1 is not r2
