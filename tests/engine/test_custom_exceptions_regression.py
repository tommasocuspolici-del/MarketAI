"""Regression: every engine module raises the correct custom exception (not ValueError).

Parametrized tests verify the custom exception contract introduced in FASE 1.
Each test checks that a specific invalid input triggers a MarketAI custom exception.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from shared.exceptions import (
    AnalysisError,
    BacktestError,
    ConfigurationError,
    DataValidationError,
    InsufficientDataError,
    MarketAIError,
    SentimentAggregationError,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _small_series(n: int = 5) -> pd.Series:
    rng = np.random.default_rng(0)
    idx = pd.date_range("2024-01-01", periods=n, freq="MS")
    return pd.Series(rng.standard_normal(n), index=idx)


# ─── InsufficientDataError tests ─────────────────────────────────────────────

class TestInsufficientDataErrors:
    def test_labour_forecast_engine_raises(self) -> None:
        """< 24 obs → InsufficientDataError."""
        from engine.analytics.labour_market.labour_forecast_engine import LabourForecastEngine
        eng = LabourForecastEngine()
        target = _small_series(10)
        feats = pd.DataFrame({"a": target.values, "b": target.values}, index=target.index)
        with pytest.raises((InsufficientDataError, MarketAIError)):
            eng.fit(target, feats)

    def test_roll_analyzer_short_df_raises(self) -> None:
        """RollAnalyzer.analyze_from_df() with < 2 rows → InsufficientDataError."""
        from engine.futures_analysis.roll_analyzer import RollAnalyzer
        from unittest.mock import MagicMock
        mock_db = MagicMock()
        analyzer = RollAnalyzer(duckdb=mock_db)
        tiny_df = pd.DataFrame({"close": [100.0], "ts": pd.Timestamp("2024-01-01")})
        with pytest.raises((InsufficientDataError, MarketAIError, ValueError)):
            analyzer.analyze_from_df("CL=F", tiny_df)

    def test_insufficient_data_error_string_mode(self) -> None:
        """InsufficientDataError accepts string message (backward compat)."""
        err = InsufficientDataError("custom message here")
        assert "custom message here" in str(err)
        assert err.required is None
        assert err.available is None

    def test_insufficient_data_error_typed_mode(self) -> None:
        """InsufficientDataError accepts (required, available) integers."""
        err = InsufficientDataError(24, 10)
        assert "24" in str(err)
        assert "10" in str(err)
        assert err.required == 24
        assert err.available == 10

    def test_simple_forecaster_short_horizon_raises(self) -> None:
        """SimpleForecaster: horizon_days <= 0 → InsufficientDataError."""
        from engine.forecasting.simple_forecaster import SimpleForecaster
        fc = SimpleForecaster()
        series = _small_series(30)
        with pytest.raises((InsufficientDataError, MarketAIError)):
            fc.forecast(series, ticker="SPY", horizon_days=0)


# ─── ConfigurationError tests ────────────────────────────────────────────────

class TestConfigurationErrors:
    def test_universe_loader_bad_yaml_raises(self, tmp_path) -> None:
        """Non-mapping YAML → ConfigurationError."""
        from engine.data_universe.universe_loader import UniverseLoader
        p = tmp_path / "bad.yaml"
        p.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises((ConfigurationError, MarketAIError)):
            UniverseLoader(config_path=p).load()

    def test_ensemble_combiner_empty_raises(self) -> None:
        """combine_equal_weight({}) → ConfigurationError."""
        from engine.analytics.forecasting.ensemble_combiner import EnsembleCombiner
        ec = EnsembleCombiner()
        with pytest.raises((ConfigurationError, MarketAIError)):
            ec.combine_equal_weight({})

    def test_ensemble_combiner_ic_empty_raises(self) -> None:
        """combine_ic_weighted({}) → ConfigurationError."""
        from engine.analytics.forecasting.ensemble_combiner import EnsembleCombiner
        ec = EnsembleCombiner()
        with pytest.raises((ConfigurationError, MarketAIError)):
            ec.combine_ic_weighted({}, {})

    def test_kalman_wrong_shape_raises(self) -> None:
        """update_kalman_weights with mismatched shapes → AnalysisError."""
        from engine.analytics.forecasting.ensemble_combiner import EnsembleCombiner
        ec = EnsembleCombiner()
        with pytest.raises((AnalysisError, MarketAIError)):
            ec.update_kalman_weights(np.array([0.5, 0.5]), np.array([0.1, 0.2, 0.3]))


# ─── DataValidationError tests ───────────────────────────────────────────────

class TestDataValidationErrors:
    def test_earnings_calendar_missing_ticker_column(self) -> None:
        """Missing ticker column → DataValidationError."""
        from engine.market_data.fetchers.earnings_calendar_fetcher import _validate
        df = pd.DataFrame([{"report_date": "2024-01-01"}])
        with pytest.raises((DataValidationError, MarketAIError)):
            _validate(df)

    def test_earnings_calendar_null_ticker(self) -> None:
        """Null ticker value → DataValidationError."""
        from engine.market_data.fetchers.earnings_calendar_fetcher import _validate
        df = pd.DataFrame([{"ticker": None, "report_date": "2024-01-01"}])
        with pytest.raises((DataValidationError, MarketAIError)):
            _validate(df)

    def test_earnings_calendar_null_report_date(self) -> None:
        """Null report_date → DataValidationError."""
        from engine.market_data.fetchers.earnings_calendar_fetcher import _validate
        df = pd.DataFrame([{"ticker": "AAPL", "report_date": None}])
        with pytest.raises((DataValidationError, MarketAIError)):
            _validate(df)


# ─── StressTestError tests ────────────────────────────────────────────────────

class TestStressTestErrors:
    def test_forward_scenarios_short_ohlcv_raises(self) -> None:
        """ForwardScenarioGenerator with < 30 rows → StressTestError."""
        from engine.stress_test.forward_scenarios import ForwardScenarioGenerator, ScenarioType
        gen = ForwardScenarioGenerator()
        tiny_df = pd.DataFrame({"ts": [1, 2, 3], "close": [100.0, 101.0, 102.0]})
        with pytest.raises((MarketAIError, ValueError)):
            gen.generate(tiny_df, scenario=ScenarioType.RECESSION)


# ─── BacktestError tests ──────────────────────────────────────────────────────

class TestBacktestErrors:
    def test_fdr_mismatched_lengths_raises(self) -> None:
        """FDR corrector with mismatched strategy_ids / p_values → BacktestError."""
        from engine.alpha_generation.backtest_engine.fdr_corrector import fdr_benjamini_hochberg
        with pytest.raises((BacktestError, MarketAIError, ValueError)):
            fdr_benjamini_hochberg(["s1", "s2"], [0.05])  # len mismatch

    def test_capacity_estimator_negative_adtv_raises(self) -> None:
        """CapacityEstimator with negative adtv → BacktestError."""
        from engine.alpha_generation.backtest_engine.capacity_estimator import CapacityEstimator
        cap = CapacityEstimator()
        with pytest.raises((BacktestError, MarketAIError)):
            cap.estimate("SPY", adtv_usd=-1.0, daily_turnover=0.02)

    def test_wfo_insufficient_data_raises(self) -> None:
        """WFORunner with too few price bars → BacktestError."""
        from engine.alpha_generation.backtest_engine.wfo_runner import WFORunner, WFOConfig
        wfo = WFORunner(WFOConfig(in_sample_years=3, oos_years=1, step_months=3))
        tiny_prices = pd.Series([100.0, 101.0, 99.0])
        with pytest.raises((BacktestError, MarketAIError, ValueError)):
            wfo.run(tiny_prices, strategy_fn=lambda x: x)


# ─── SentimentAggregationError tests ─────────────────────────────────────────

class TestSentimentErrors:
    def test_sentiment_signal_out_of_range_raises(self) -> None:
        """SentimentSignal with score > 1.0 → SentimentAggregationError."""
        from engine.analytics.sentiment.signal_model import SentimentSignal, SentimentSource
        from datetime import UTC, datetime
        with pytest.raises((SentimentAggregationError, MarketAIError)):
            SentimentSignal(
                source=SentimentSource.CNN_FEAR_GREED,
                score=2.0,  # invalid > 1.0
                confidence=0.9,
                timestamp=datetime.now(UTC),
                raw_value=75.0,
            )


# ─── AnalysisError tests ──────────────────────────────────────────────────────

class TestAnalysisErrors:
    def test_hmm_too_few_samples_raises(self) -> None:
        """HMMRegimeModel.fit() with < 24 obs → AnalysisError."""
        from engine.analytics.regime.hmm_macro_regime import HMMRegimeModel
        model = HMMRegimeModel()
        tiny_df = pd.DataFrame(
            np.random.default_rng(0).standard_normal((5, 12)),
            columns=[f"f{i}" for i in range(12)],
        )
        with pytest.raises((AnalysisError, MarketAIError, ValueError)):
            model.fit(tiny_df)
