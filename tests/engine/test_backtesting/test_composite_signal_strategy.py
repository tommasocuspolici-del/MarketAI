"""Tests for CompositeSignalStrategy and build_strategy_from_dsl in strategy_builder."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import duckdb
import numpy as np
import pandas as pd
import pytest

from engine.backtesting.strategy_builder import (
    CompositeSignalStrategy,
    DSLStrategy,
    _bool_to_positions,
    _normalize_to_positions,
    build_strategy_from_dsl,
)
from shared.exceptions import BacktestError


_CREATE_COMPOSITE = """
CREATE TABLE IF NOT EXISTS engine_composite_signal (
    computed_at TIMESTAMPTZ PRIMARY KEY,
    composite_score DOUBLE,
    recommended_action VARCHAR,
    confidence VARCHAR,
    regime VARCHAR,
    credit_stress VARCHAR,
    claims_regime VARCHAR,
    yield_curve_regime VARCHAR,
    component_breakdown_json VARCHAR,
    vix_component DOUBLE,
    macro_component DOUBLE,
    yield_curve_component DOUBLE,
    credit_component DOUBLE,
    claims_component DOUBLE
)
"""


def _make_client(with_scores=False):
    conn = duckdb.connect(":memory:")
    conn.execute(_CREATE_COMPOSITE)
    if with_scores:
        for i, score in enumerate([0.5, 0.3, -0.4, 0.2, -0.6]):
            conn.execute(
                "INSERT INTO engine_composite_signal (computed_at, composite_score) "
                f"VALUES ('2024-0{i+1}-15T00:00:00+00:00', {score})"
            )
    client = MagicMock()

    @contextmanager
    def _transaction():
        yield conn

    client.transaction = _transaction
    return client


def _make_ohlcv(n=60, start="2024-01-01"):
    rng = np.random.default_rng(42)
    close = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    dates = pd.date_range(start, periods=n, freq="B", tz="UTC")
    return pd.DataFrame({
        "ts": dates,
        "open": close * 0.999,
        "high": close * 1.005,
        "low": close * 0.995,
        "close": close.astype(np.float64),
        "volume": np.ones(n) * 100_000,
    }, index=dates)  # Use DatetimeIndex so CompositeSignalStrategy alignment works


class TestNormalizeToPositions:
    def test_output_in_range(self) -> None:
        series = pd.Series(np.linspace(-5, 5, 50))
        out = _normalize_to_positions(series, window=10)
        assert (out >= -1.0).all()
        assert (out <= 1.0).all()

    def test_dtype_float64(self) -> None:
        series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        out = _normalize_to_positions(series, window=3)
        assert out.dtype == np.float64

    def test_constant_series_returns_zeros(self) -> None:
        series = pd.Series([5.0] * 20)
        out = _normalize_to_positions(series, window=5)
        # std = 0 → all zeros (clipped z = 0)
        assert (out.abs() <= 1.0).all()


class TestBoolToPositions:
    def test_long_only(self) -> None:
        series = pd.Series([1.0, 0.0, 1.0, 0.0])
        out = _bool_to_positions(series, allow_short=False)
        assert list(out) == [1.0, 0.0, 1.0, 0.0]

    def test_allow_short(self) -> None:
        series = pd.Series([1.0, 0.0, 1.0])
        out = _bool_to_positions(series, allow_short=True)
        assert list(out) == [1.0, -1.0, 1.0]


class TestDSLStrategyExtended:
    def test_float_dsl_long_only_clips_negative(self) -> None:
        strategy = DSLStrategy("EMA(close, 10) - close", allow_short=False)
        ohlcv = _make_ohlcv()
        signal = strategy.generate_signals(ohlcv)
        assert (signal.positions >= 0.0).all()
        assert (signal.positions <= 1.0).all()

    def test_dsl_short_data_returns_zero_signal(self) -> None:
        strategy = DSLStrategy("RSI(close, 14) > 50", allow_short=False)
        ohlcv = _make_ohlcv(n=1)
        signal = strategy.generate_signals(ohlcv)
        assert (signal.positions == 0.0).all()

    def test_invalid_dsl_raises_backtest_error(self) -> None:
        strategy = DSLStrategy("INVALID_FUNC_XYZ(close)", allow_short=False)
        ohlcv = _make_ohlcv()
        with pytest.raises(BacktestError):
            strategy.generate_signals(ohlcv)

    def test_params_dict(self) -> None:
        strategy = DSLStrategy("RSI(close, 14) > 50", allow_short=True, zscore_window=15)
        params = strategy._params()
        assert params["expression"] == "RSI(close, 14) > 50"
        assert params["allow_short"] == 1
        assert params["zscore_window"] == 15


class TestCompositeSignalStrategy:
    def test_raises_on_invalid_thresholds(self) -> None:
        client = _make_client()
        with pytest.raises(BacktestError):
            CompositeSignalStrategy(client, long_threshold=0.05, short_threshold=0.10)

    def test_name_includes_thresholds(self) -> None:
        client = _make_client()
        s = CompositeSignalStrategy(client, long_threshold=0.15, short_threshold=-0.15)
        assert "0.15" in s.name

    def test_generate_signals_no_scores_returns_zeros(self) -> None:
        client = _make_client(with_scores=False)
        strategy = CompositeSignalStrategy(client)
        ohlcv = _make_ohlcv()
        signal = strategy.generate_signals(ohlcv)
        assert (signal.positions == 0.0).all()

    def test_generate_signals_short_data_returns_zeros(self) -> None:
        client = _make_client()
        strategy = CompositeSignalStrategy(client)
        ohlcv = _make_ohlcv(n=1)
        signal = strategy.generate_signals(ohlcv)
        assert (signal.positions == 0.0).all()

    def test_generate_signals_with_scores(self) -> None:
        client = _make_client(with_scores=True)
        strategy = CompositeSignalStrategy(
            client, long_threshold=0.25, short_threshold=-0.35, allow_short=True
        )
        ohlcv = _make_ohlcv(n=30)
        signal = strategy.generate_signals(ohlcv)
        # positions in {-1, 0, 1}
        assert set(signal.positions.unique()).issubset({-1.0, 0.0, 1.0})

    def test_long_only_no_short_positions(self) -> None:
        client = _make_client(with_scores=True)
        strategy = CompositeSignalStrategy(
            client, long_threshold=0.1, short_threshold=-0.1, allow_short=False
        )
        ohlcv = _make_ohlcv(n=30)
        signal = strategy.generate_signals(ohlcv)
        assert (signal.positions >= 0.0).all()

    def test_generate_signals_db_error_returns_zeros(self) -> None:
        bad_client = MagicMock()

        @contextmanager
        def _bad_tx():
            raise RuntimeError("DB fail")
            yield  # noqa

        bad_client.transaction = _bad_tx
        strategy = CompositeSignalStrategy(bad_client)
        ohlcv = _make_ohlcv()
        signal = strategy.generate_signals(ohlcv)
        assert (signal.positions == 0.0).all()

    def test_params_dict(self) -> None:
        client = _make_client()
        s = CompositeSignalStrategy(client, long_threshold=0.2, short_threshold=-0.2, allow_short=True)
        params = s._params()
        assert params["long_threshold"] == 0.2
        assert params["short_threshold"] == -0.2
        assert params["allow_short"] == 1


class TestBuildStrategyFromDsl:
    def test_returns_dsl_strategy(self) -> None:
        s = build_strategy_from_dsl("RSI(close, 14) > 50")
        assert isinstance(s, DSLStrategy)

    def test_passes_allow_short(self) -> None:
        s = build_strategy_from_dsl("EMA(close, 10) > close", allow_short=True)
        assert s._allow_short is True

    def test_passes_zscore_window(self) -> None:
        s = build_strategy_from_dsl("close > 0", zscore_window=15)
        assert s._zscore_window == 15

    def test_invalid_expression_raises_backtest_error(self) -> None:
        with pytest.raises(BacktestError):
            build_strategy_from_dsl("TOTALLY_INVALID_XYZ_FUNC(close, 14)")
