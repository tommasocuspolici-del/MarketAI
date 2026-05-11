"""Tests for engine.backtesting.engine — backtest engine + walk-forward."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from engine.backtesting import (
    MIN_FEES,
    MIN_SLIPPAGE,
    BacktestEngine,
    BacktestResult,
    WalkForwardResult,
)
from engine.backtesting.strategies import MovingAverageCrossover
from shared.db.quality import DataQualityReport
from shared.exceptions import BacktestError, DataQualityError


def _ohlcv(n: int = 252, seed: int = 42, drift: float = 0.0008) -> pd.DataFrame:
    """Generate a realistic random-walk OHLCV DataFrame."""
    rng = np.random.default_rng(seed=seed)
    ts = pd.date_range(start="2024-01-01", periods=n, freq="D", tz="UTC")
    log_ret = rng.normal(drift, 0.012, size=n)
    close = 100.0 * np.exp(np.cumsum(log_ret))
    return pd.DataFrame(
        {
            "ts": ts, "open": close * 0.999, "high": close * 1.005,
            "low": close * 0.995, "close": close,
            "volume": [1_000_000] * n, "adj_close": close,
        }
    )


# ═══════════════════════════════════════════════════════════════════════════
# Construction
# ═══════════════════════════════════════════════════════════════════════════
class TestEngineConstruction:
    def test_default_meets_rule_23(self) -> None:
        engine = BacktestEngine()
        assert engine._fees >= MIN_FEES
        assert engine._slippage >= MIN_SLIPPAGE

    def test_below_min_fees_rejected(self) -> None:
        # Regola 23: fees < 0.001 vietate
        with pytest.raises(BacktestError, match="fees"):
            BacktestEngine(fees=0.0005)

    def test_below_min_slippage_rejected(self) -> None:
        with pytest.raises(BacktestError, match="slippage"):
            BacktestEngine(slippage=0.0005)

    def test_negative_initial_cash_rejected(self) -> None:
        with pytest.raises(BacktestError, match="initial_cash"):
            BacktestEngine(initial_cash=-100.0)


# ═══════════════════════════════════════════════════════════════════════════
# Single backtest
# ═══════════════════════════════════════════════════════════════════════════
class TestRunBacktest:
    def test_run_returns_backtest_result(self) -> None:
        engine = BacktestEngine()
        ohlcv = _ohlcv(252)
        result = engine.run(ohlcv, MovingAverageCrossover(), ticker="TEST")
        assert isinstance(result, BacktestResult)
        assert result.strategy_name.startswith("MA_cross")
        assert len(result.equity_curve) == 252

    def test_anti_lookahead_shift(self) -> None:
        """Regola 23: la posizione al tempo t deve usare segnali di t-1."""
        engine = BacktestEngine()
        ohlcv = _ohlcv(100)
        result = engine.run(ohlcv, MovingAverageCrossover(fast=5, slow=20))
        # La prima posizione realizzata deve essere 0 (nessun segnale precedente)
        assert result.positions.iloc[0] == 0.0

    def test_fees_applied(self) -> None:
        engine = BacktestEngine(fees=0.001, slippage=0.001)
        ohlcv = _ohlcv(200)
        result = engine.run(ohlcv, MovingAverageCrossover(fast=5, slow=20))
        # Se ci sono trade, deve esserci una somma di fees > 0
        if result.n_trades > 0:
            assert result.fees_total > 0.0

    def test_quality_score_below_threshold_rejected(self) -> None:
        """Regola 26: backtest rifiutato se quality < 0.7."""
        engine = BacktestEngine()
        ohlcv = _ohlcv(100)
        bad_quality = DataQualityReport(
            series_id="BAD", series_kind="prices",
            quality_score=0.5, total_rows=100,
        )
        with pytest.raises(DataQualityError):
            engine.run(ohlcv, MovingAverageCrossover(), quality_report=bad_quality)

    def test_quality_score_above_threshold_accepted(self) -> None:
        engine = BacktestEngine()
        ohlcv = _ohlcv(100)
        good_quality = DataQualityReport(
            series_id="GOOD", series_kind="prices",
            quality_score=0.85, total_rows=100,
        )
        # Non deve sollevare
        result = engine.run(ohlcv, MovingAverageCrossover(), quality_report=good_quality)
        assert result.performance.n_periods > 0

    def test_short_data_rejected(self) -> None:
        engine = BacktestEngine()
        with pytest.raises(BacktestError, match="at least 2"):
            engine.run(_ohlcv(1), MovingAverageCrossover())

    def test_missing_close_rejected(self) -> None:
        engine = BacktestEngine()
        bad = pd.DataFrame({"ts": pd.date_range("2025-01-01", periods=10, tz="UTC")})
        with pytest.raises(BacktestError, match="close"):
            engine.run(bad, MovingAverageCrossover())

    def test_equity_curve_starts_near_initial_cash(self) -> None:
        engine = BacktestEngine(initial_cash=10_000.0)
        ohlcv = _ohlcv(100)
        result = engine.run(ohlcv, MovingAverageCrossover())
        # Il primo punto della equity curve deve essere ~10_000 (no trade ancora)
        # Tolleranza: il primo bar applica eventualmente pos_change=0 → identità
        assert abs(result.equity_curve.iloc[0] - 10_000.0) / 10_000.0 < 0.01


# ═══════════════════════════════════════════════════════════════════════════
# Walk-forward
# ═══════════════════════════════════════════════════════════════════════════
class TestWalkForward:
    def test_walk_forward_returns_result(self) -> None:
        engine = BacktestEngine()
        ohlcv = _ohlcv(500)
        wf = engine.walk_forward(ohlcv, MovingAverageCrossover(fast=5, slow=20), n_splits=5)
        assert isinstance(wf, WalkForwardResult)
        assert wf.n_splits >= 3  # almeno alcuni split utilizzabili
        assert len(wf.split_results) == wf.n_splits

    def test_walk_forward_too_few_splits_rejected(self) -> None:
        engine = BacktestEngine()
        with pytest.raises(BacktestError, match="n_splits"):
            engine.walk_forward(_ohlcv(500), MovingAverageCrossover(), n_splits=1)

    def test_walk_forward_short_data_rejected(self) -> None:
        engine = BacktestEngine()
        with pytest.raises(BacktestError, match="100 bars"):
            engine.walk_forward(_ohlcv(50), MovingAverageCrossover())

    def test_walk_forward_invalid_train_pct(self) -> None:
        engine = BacktestEngine()
        with pytest.raises(BacktestError, match="train_pct"):
            engine.walk_forward(_ohlcv(500), MovingAverageCrossover(), train_pct=0.05)


# ═══════════════════════════════════════════════════════════════════════════
# Performance benchmarks (DoD Fase 4)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.benchmark
class TestBenchmarks:
    """DoD Fase 4 latency targets."""

    def test_10y_backtest_under_2s(self) -> None:
        """Single ticker backtest 10 years < 2s."""
        engine = BacktestEngine()
        # 10 anni di daily ≈ 2520 barre
        ohlcv = _ohlcv(2520, seed=7)
        strategy = MovingAverageCrossover(fast=20, slow=50)

        t0 = time.monotonic()
        engine.run(ohlcv, strategy, ticker="SPY")
        elapsed_ms = (time.monotonic() - t0) * 1000

        # Target DoD: < 2000ms
        assert elapsed_ms < 2000, f"expected <2000ms, got {elapsed_ms:.1f}ms"

    def test_walk_forward_5_splits_under_15s(self) -> None:
        """Walk-forward 5 splits < 15s."""
        engine = BacktestEngine()
        ohlcv = _ohlcv(2520, seed=7)
        strategy = MovingAverageCrossover(fast=20, slow=50)

        t0 = time.monotonic()
        engine.walk_forward(ohlcv, strategy, n_splits=5)
        elapsed_ms = (time.monotonic() - t0) * 1000

        assert elapsed_ms < 15000, f"expected <15000ms, got {elapsed_ms:.1f}ms"
