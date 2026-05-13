"""Tests per strategy_builder, backtest_runner, forward_scenarios.

Roadmap v3.0 — Settimana 9 (Regola 23 + 24).

Tutti i test sono offline (no DuckDB reale, no network).
Focus:
  · DSLStrategy: correttezza posizioni, no lookahead, range [-1,1]
  · CompositeSignalStrategy: allineamento ts, forward-fill corretto
  · ForwardScenarioGenerator: deterministico, struttura output preservata
  · StressTestRunner: 5 scenari, fees/slippage enforcement
  · BacktestConfig: serializzazione JSON
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import duckdb
import numpy as np
import pandas as pd
import pytest


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def ohlcv_100() -> pd.DataFrame:
    """100 barre OHLCV deterministiche con trend rialzista."""
    rng   = np.random.default_rng(7)
    n     = 100
    close = 100.0 + np.cumsum(rng.normal(0.05, 0.8, n))
    dates = pd.date_range("2024-01-01", periods=n, freq="B", tz="UTC")
    return pd.DataFrame({
        "ts":     dates,
        "open":   close * 0.999,
        "high":   close * 1.005,
        "low":    close * 0.995,
        "close":  close.astype(np.float64),
        "volume": np.ones(n) * 500_000,
    })


@pytest.fixture
def in_memory_client():
    """DuckDB in-memory con schema backtest_results (migration 016)."""
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE backtest_results (
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
    """)
    conn.execute("""
        CREATE TABLE engine_composite_signal (
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
    """)
    client = MagicMock()

    @contextmanager
    def _transaction():
        yield conn

    def _query(sql, params=None):
        return conn.execute(sql, params or []).fetchall()

    client.transaction = _transaction
    client.query = _query
    return client


# ─── Test: DSLStrategy ───────────────────────────────────────────────────────

class TestDSLStrategy:
    """Tests per DSLStrategy (Regola 23: anti-lookahead, range [-1,1])."""

    def test_boolean_dsl_long_only(self, ohlcv_100) -> None:
        """DSL booleano → posizioni in {0, 1} (long-only)."""
        from engine.backtesting.strategy_builder import DSLStrategy
        strategy = DSLStrategy("RSI(close, 14) > 50", allow_short=False)
        signal   = strategy.generate_signals(ohlcv_100)
        unique   = set(signal.positions.dropna().unique())
        assert unique.issubset({0.0, 1.0})

    def test_float_dsl_positions_in_range(self, ohlcv_100) -> None:
        """DSL float → posizioni in [-1, 1]."""
        from engine.backtesting.strategy_builder import DSLStrategy
        strategy = DSLStrategy("MACD(close, 12, 26, 9)", allow_short=True)
        signal   = strategy.generate_signals(ohlcv_100)
        positions = signal.positions.dropna()
        assert (positions >= -1.0).all() and (positions <= 1.0).all()

    def test_dsl_strategy_name_contains_expression(self) -> None:
        """Il nome della strategia contiene l'espressione."""
        from engine.backtesting.strategy_builder import DSLStrategy
        s = DSLStrategy("EMA(close, 20)", allow_short=False)
        assert "DSL_" in s.name

    def test_empty_expression_raises(self) -> None:
        """Espressione vuota → BacktestError."""
        from engine.backtesting.strategy_builder import DSLStrategy
        from shared.exceptions import BacktestError
        with pytest.raises(BacktestError):
            DSLStrategy("", allow_short=False)

    def test_short_series_returns_zero_signal(self) -> None:
        """Serie troppo corta → segnale zero (no errore)."""
        from engine.backtesting.strategy_builder import DSLStrategy
        s = DSLStrategy("EMA(close, 20)")
        ohlcv = pd.DataFrame({
            "ts": pd.date_range("2024-01-01", periods=1, freq="D", tz="UTC"),
            "close": [100.0],
        })
        signal = s.generate_signals(ohlcv)
        assert (signal.positions == 0.0).all()

    def test_positions_not_shifted(self, ohlcv_100) -> None:
        """La Strategy NON deve shiftare i segnali (lo fa BacktestEngine).

        Verifica che la posizione al tempo t usa solo dati fino a t.
        Il check consiste nel verificare che la series ha la stessa lunghezza
        dell'input (shift(1) avrebbe spostato gli indici).
        """
        from engine.backtesting.strategy_builder import DSLStrategy
        s = DSLStrategy("SMA(close, 5) > close")
        signal = s.generate_signals(ohlcv_100)
        assert len(signal.positions) == len(ohlcv_100)

    def test_build_strategy_from_dsl_factory(self) -> None:
        """build_strategy_from_dsl() valida l'espressione alla costruzione."""
        from engine.backtesting.strategy_builder import build_strategy_from_dsl
        s = build_strategy_from_dsl("RSI(close, 14) > 70")
        assert s is not None

    def test_build_strategy_from_dsl_invalid_raises(self) -> None:
        """Espressione non valida → BacktestError dalla factory."""
        from engine.backtesting.strategy_builder import build_strategy_from_dsl
        from shared.exceptions import BacktestError
        with pytest.raises(BacktestError):
            build_strategy_from_dsl("EVIL_FUNCTION(close, 99)")

    def test_dsl_strategy_params_are_serializable(self, ohlcv_100) -> None:
        """I params devono essere JSON-serializzabili (per persistenza)."""
        import json
        from engine.backtesting.strategy_builder import DSLStrategy
        s = DSLStrategy("EMA(close, 20) > close")
        sig = s.generate_signals(ohlcv_100)
        json.dumps(sig.params)  # non deve lanciare


# ─── Test: ForwardScenarioGenerator ──────────────────────────────────────────

class TestForwardScenarioGenerator:
    """Tests per ForwardScenarioGenerator (Regola 24)."""

    def test_generate_returns_dataframe_same_length(self, ohlcv_100) -> None:
        """Lo scenario stressed ha la stessa lunghezza dell'input."""
        from engine.stress_test.forward_scenarios import (
            ForwardScenarioGenerator, ScenarioType,
        )
        gen = ForwardScenarioGenerator()
        stressed = gen.generate(ohlcv_100, ScenarioType.RECESSION)
        assert len(stressed) == len(ohlcv_100)

    def test_generate_same_columns_as_input(self, ohlcv_100) -> None:
        """Lo schema dell'output è identico all'input (stesse colonne)."""
        from engine.stress_test.forward_scenarios import (
            ForwardScenarioGenerator, ScenarioType,
        )
        gen = ForwardScenarioGenerator()
        stressed = gen.generate(ohlcv_100, ScenarioType.INFLATION_SHOCK)
        assert set(stressed.columns) == set(ohlcv_100.columns)

    def test_generate_same_starting_price(self, ohlcv_100) -> None:
        """Il prezzo iniziale (close[0]) è invariato dopo lo stress."""
        from engine.stress_test.forward_scenarios import (
            ForwardScenarioGenerator, ScenarioType,
        )
        gen = ForwardScenarioGenerator()
        stressed = gen.generate(ohlcv_100, ScenarioType.CREDIT_CRISIS)
        orig_start = float(ohlcv_100["close"].iloc[0])
        stress_start = float(stressed["close"].iloc[0])
        assert stress_start == pytest.approx(orig_start, rel=1e-6)

    def test_generate_deterministic(self, ohlcv_100) -> None:
        """Lo stesso scenario produce sempre lo stesso output (seed fisso)."""
        from engine.stress_test.forward_scenarios import (
            ForwardScenarioGenerator, ScenarioType,
        )
        gen = ForwardScenarioGenerator()
        r1 = gen.generate(ohlcv_100, ScenarioType.GOLDILOCKS)["close"].values
        r2 = gen.generate(ohlcv_100, ScenarioType.GOLDILOCKS)["close"].values
        np.testing.assert_array_equal(r1, r2)

    def test_generate_all_returns_all_scenarios(self, ohlcv_100) -> None:
        """generate_all() ritorna tutti e 5 gli scenari."""
        from engine.stress_test.forward_scenarios import (
            ForwardScenarioGenerator, ScenarioType,
        )
        gen = ForwardScenarioGenerator()
        all_results = gen.generate_all(ohlcv_100)
        expected = {s.value for s in ScenarioType}
        assert expected.issubset(set(all_results.keys()))

    def test_recession_worse_than_goldilocks(self, ohlcv_100) -> None:
        """Il scenario recessione produce rendimenti peggiori del goldilocks."""
        from engine.stress_test.forward_scenarios import (
            ForwardScenarioGenerator, ScenarioType,
        )
        gen = ForwardScenarioGenerator()
        rec  = gen.generate(ohlcv_100, ScenarioType.RECESSION)["close"]
        gold = gen.generate(ohlcv_100, ScenarioType.GOLDILOCKS)["close"]
        # Resa finale: goldilocks > recession (con alta probabilità)
        rec_return  = float(rec.iloc[-1] / rec.iloc[0] - 1)
        gold_return = float(gold.iloc[-1] / gold.iloc[0] - 1)
        assert gold_return > rec_return

    def test_short_ohlcv_raises(self) -> None:
        """OHLCV troppo corto → ValueError."""
        from engine.stress_test.forward_scenarios import (
            ForwardScenarioGenerator, ScenarioType,
        )
        gen = ForwardScenarioGenerator()
        tiny = pd.DataFrame({"ts": [1, 2, 3], "close": [100.0, 101.0, 102.0]})
        with pytest.raises(ValueError, match="troppo corto"):
            gen.generate(tiny, ScenarioType.BASE)


# ─── Test: StressTestRunner ───────────────────────────────────────────────────

class TestStressTestRunner:
    """Tests per StressTestRunner (Regola 24)."""

    def test_run_all_scenarios_returns_dict(self, ohlcv_100) -> None:
        """run_all_scenarios() ritorna un dict non vuoto."""
        from engine.backtesting.strategies.ma_cross import MovingAverageCrossover
        from engine.stress_test.forward_scenarios import StressTestRunner

        runner   = StressTestRunner()
        strategy = MovingAverageCrossover(fast=5, slow=20)
        results  = runner.run_all_scenarios(strategy, ohlcv_100, ticker="SPY")
        assert isinstance(results, dict)
        assert len(results) >= 5

    def test_base_scenario_always_present(self, ohlcv_100) -> None:
        """Lo scenario 'base' è sempre presente come benchmark."""
        from engine.backtesting.strategies.ma_cross import MovingAverageCrossover
        from engine.stress_test.forward_scenarios import StressTestRunner

        runner   = StressTestRunner()
        strategy = MovingAverageCrossover(fast=5, slow=20)
        results  = runner.run_all_scenarios(strategy, ohlcv_100)
        assert "base" in results

    def test_compare_scenarios_returns_dataframe(self, ohlcv_100) -> None:
        """compare_scenarios() ritorna DataFrame ordinato per sharpe."""
        from engine.backtesting.strategies.ma_cross import MovingAverageCrossover
        from engine.stress_test.forward_scenarios import StressTestRunner

        runner   = StressTestRunner()
        strategy = MovingAverageCrossover(fast=5, slow=20)
        results  = runner.run_all_scenarios(strategy, ohlcv_100)
        df       = runner.compare_scenarios(results)
        assert isinstance(df, pd.DataFrame)
        assert "scenario" in df.columns
        assert "sharpe" in df.columns

    def test_fees_below_minimum_raises(self) -> None:
        """fees < 0.001 → BacktestError (Regola 23)."""
        from engine.stress_test.forward_scenarios import StressTestRunner
        from shared.exceptions import BacktestError
        with pytest.raises(BacktestError, match="Rule 23"):
            StressTestRunner(fees=0.0001)


# ─── Test: BacktestConfig ─────────────────────────────────────────────────────

class TestBacktestConfig:
    """Tests per BacktestConfig serializzazione."""

    def test_to_json_is_valid_json(self) -> None:
        import json
        from engine.backtesting.backtest_runner import BacktestConfig
        cfg = BacktestConfig(ticker="AAPL", scenario="recession")
        parsed = json.loads(cfg.to_json())
        assert parsed["ticker"] == "AAPL"
        assert parsed["scenario"] == "recession"

    def test_default_fees_slippage(self) -> None:
        """I default di fees e slippage rispettano la Regola 23."""
        from engine.backtesting.backtest_runner import BacktestConfig
        from engine.backtesting.engine import MIN_FEES, MIN_SLIPPAGE
        cfg = BacktestConfig(ticker="SPY")
        assert cfg.fees >= MIN_FEES
        assert cfg.slippage >= MIN_SLIPPAGE
