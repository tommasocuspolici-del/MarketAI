"""Tests for engine.backtesting.results_repo."""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pytest

from engine.backtesting import (
    BacktestEngine,
    BacktestResultsRepository,
)
from engine.backtesting.strategies import MovingAverageCrossover
from shared.constants import MIGRATIONS_DUCKDB_DIR
from shared.db.duckdb_client import DuckDBClient
from shared.db.duckdb_migrator import DuckDBMigrator

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def repo(tmp_duckdb_path: Path) -> BacktestResultsRepository:
    """Fresh DuckDB with schema applied + repo bound to it."""
    client = DuckDBClient(path=tmp_duckdb_path)
    DuckDBMigrator(client=client, migrations_dir=MIGRATIONS_DUCKDB_DIR).apply_pending()
    return BacktestResultsRepository(client=client)


def _ohlcv(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(seed=42)
    ts = pd.date_range(start="2024-01-01", periods=n, freq="D", tz="UTC")
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.001, 0.012, size=n)))
    return pd.DataFrame(
        {
            "ts": ts, "open": close, "high": close * 1.01, "low": close * 0.99,
            "close": close, "volume": [1_000_000] * n,
        }
    )


@pytest.fixture
def sample_result() -> object:
    """Generate a single backtest result for persistence tests."""
    engine = BacktestEngine()
    ohlcv = _ohlcv(200)
    return engine.run(ohlcv, MovingAverageCrossover(fast=5, slow=20), ticker="AAPL")


class TestSaveResult:
    def test_save_returns_uuid(
        self, repo: BacktestResultsRepository, sample_result: object
    ) -> None:
        backtest_id = repo.save_result(
            sample_result,  # type: ignore[arg-type]
            timeframe="1d",
            fees=0.001,
            slippage=0.001,
            strategy_params={"fast": 5, "slow": 20},
        )
        assert isinstance(backtest_id, str)
        assert len(backtest_id) == 36  # UUID format

    def test_count_increments(
        self, repo: BacktestResultsRepository, sample_result: object
    ) -> None:
        assert repo.count() == 0
        repo.save_result(sample_result)  # type: ignore[arg-type]
        assert repo.count() == 1
        repo.save_result(sample_result)  # type: ignore[arg-type]
        assert repo.count() == 2


class TestReadByID:
    def test_round_trip(
        self, repo: BacktestResultsRepository, sample_result: object
    ) -> None:
        bid = repo.save_result(
            sample_result,  # type: ignore[arg-type]
            strategy_params={"fast": 5, "slow": 20},
        )
        row = repo.read_by_id(bid)
        assert row is not None
        assert row["backtest_id"] == bid
        assert row["ticker"] == "AAPL"
        assert row["strategy_name"].startswith("MA_cross")  # type: ignore[union-attr]

    def test_nonexistent_returns_none(self, repo: BacktestResultsRepository) -> None:
        assert repo.read_by_id("00000000-0000-0000-0000-000000000000") is None


class TestReadByTicker:
    def test_filter_by_ticker(
        self, repo: BacktestResultsRepository, sample_result: object
    ) -> None:
        repo.save_result(sample_result)  # type: ignore[arg-type]
        # Generiamo anche un risultato per un ticker diverso
        engine = BacktestEngine()
        other = engine.run(_ohlcv(200), MovingAverageCrossover(), ticker="MSFT")
        repo.save_result(other)

        results_aapl = repo.read_by_ticker("AAPL")
        assert all(r["ticker"] == "AAPL" for r in results_aapl)

    def test_limit_respected(
        self, repo: BacktestResultsRepository, sample_result: object
    ) -> None:
        for _ in range(5):
            repo.save_result(sample_result)  # type: ignore[arg-type]
        results = repo.read_by_ticker("AAPL", limit=3)
        assert len(results) == 3


class TestSaveWalkForward:
    def test_persists_all_splits(
        self, repo: BacktestResultsRepository
    ) -> None:
        engine = BacktestEngine()
        ohlcv = _ohlcv(500)
        wf = engine.walk_forward(ohlcv, MovingAverageCrossover(), n_splits=5)
        ids = repo.save_walk_forward(wf, strategy_params={"fast": 20, "slow": 50})

        assert len(ids) == wf.n_splits
        assert repo.count() == wf.n_splits
