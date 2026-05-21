"""Tests for Q1-Q5 pure loader functions — no Streamlit dependency."""
from __future__ import annotations

import pandas as pd
import pytest
from unittest.mock import MagicMock, patch


# ─── Q1 Backtesting ──────────────────────────────────────────────────────────

class TestQ1BacktestLoaders:
    def test_get_available_strategies_returns_list(self) -> None:
        from presentation.dashboard_engine.pages.Q1_Backtesting import _get_available_strategies
        result = _get_available_strategies()
        assert isinstance(result, list)
        assert len(result) >= 4

    def test_get_available_strategies_contains_expected(self) -> None:
        from presentation.dashboard_engine.pages.Q1_Backtesting import _get_available_strategies
        strategies = _get_available_strategies()
        assert "MA Cross" in strategies
        assert "RSI" in strategies

    def test_load_backtest_history_returns_dataframe(self) -> None:
        from presentation.dashboard_engine.pages.Q1_Backtesting import _load_backtest_history
        result = _load_backtest_history()
        assert isinstance(result, pd.DataFrame)

    def test_load_backtest_history_empty_on_runner_error(self) -> None:
        from presentation.dashboard_engine.pages.Q1_Backtesting import _load_backtest_history
        with patch("engine.backtesting.backtest_runner.get_backtest_runner", side_effect=RuntimeError):
            result = _load_backtest_history()
        assert result.empty

    def test_load_backtest_history_limit_param_accepted(self) -> None:
        from presentation.dashboard_engine.pages.Q1_Backtesting import _load_backtest_history
        result = _load_backtest_history(limit=5)
        assert isinstance(result, pd.DataFrame)


# ─── Q2 Stress Test ──────────────────────────────────────────────────────────

class TestQ2StressLoaders:
    def test_load_stress_scenarios_returns_nonempty_list(self) -> None:
        from presentation.dashboard_engine.pages.Q2_Stress_Test import _load_stress_scenarios
        result = _load_stress_scenarios()
        assert isinstance(result, list)
        assert len(result) >= 3

    def test_stress_scenarios_have_required_keys(self) -> None:
        from presentation.dashboard_engine.pages.Q2_Stress_Test import _load_stress_scenarios
        for s in _load_stress_scenarios():
            assert "name" in s
            assert "shock_pct" in s
            assert "duration_days" in s
            assert "description" in s

    def test_stress_scenarios_shock_pct_negative(self) -> None:
        from presentation.dashboard_engine.pages.Q2_Stress_Test import _load_stress_scenarios
        for s in _load_stress_scenarios():
            assert s["shock_pct"] < 0, f"Expected negative shock for {s['name']}"

    def test_load_risk_metrics_returns_dict(self) -> None:
        from presentation.dashboard_engine.pages.Q2_Stress_Test import _load_risk_metrics
        result = _load_risk_metrics("SPY")
        assert isinstance(result, dict)

    def test_load_risk_metrics_graceful_on_db_error(self) -> None:
        from presentation.dashboard_engine.pages.Q2_Stress_Test import _load_risk_metrics
        with patch("shared.db.duckdb_client.get_duckdb_client", side_effect=RuntimeError):
            result = _load_risk_metrics("SPY")
        assert result == {}

    def test_load_risk_metrics_keys_when_populated(self) -> None:
        from presentation.dashboard_engine.pages.Q2_Stress_Test import _load_risk_metrics
        mock_metrics = MagicMock()
        mock_metrics.var_95_tstudent = 0.02
        mock_metrics.cvar_95 = 0.03
        mock_metrics.var_99_tstudent = 0.04
        mock_metrics.cvar_99 = 0.05
        mock_metrics.skewness = -0.5
        mock_metrics.kurtosis = 3.0
        mock_metrics.data_quality_score = 0.9

        mock_calc = MagicMock()
        mock_calc.compute.return_value = mock_metrics

        with patch("engine.risk.cvar_calculator.CVaRCalculator", return_value=mock_calc), \
             patch("shared.db.duckdb_client.get_duckdb_client", return_value=MagicMock()), \
             patch("shared.db.prices_repo.PricesRepository", return_value=MagicMock()):
            result = _load_risk_metrics("SPY")

        assert isinstance(result, dict)


# ─── Q3 Correlations ─────────────────────────────────────────────────────────

class TestQ3CorrelationLoaders:
    def test_load_correlation_report_returns_dict(self) -> None:
        from presentation.dashboard_engine.pages.Q3_Correlations import _load_correlation_report
        result = _load_correlation_report()
        assert isinstance(result, dict)

    def test_load_correlation_report_empty_on_db_error(self) -> None:
        from presentation.dashboard_engine.pages.Q3_Correlations import _load_correlation_report
        with patch("shared.db.duckdb_client.get_duckdb_client", side_effect=RuntimeError):
            result = _load_correlation_report()
        assert result == {}

    def test_load_correlation_report_empty_on_analyzer_error(self) -> None:
        from presentation.dashboard_engine.pages.Q3_Correlations import _load_correlation_report
        with patch("engine.analytics.correlation.analyzer.CorrelationAnalyzer", side_effect=RuntimeError):
            result = _load_correlation_report()
        assert result == {}

    def test_load_cross_asset_snapshot_returns_dict(self) -> None:
        from presentation.dashboard_engine.pages.Q3_Correlations import _load_cross_asset_snapshot
        result = _load_cross_asset_snapshot()
        assert isinstance(result, dict)

    def test_load_cross_asset_snapshot_empty_on_db_error(self) -> None:
        from presentation.dashboard_engine.pages.Q3_Correlations import _load_cross_asset_snapshot
        with patch("shared.db.duckdb_client.get_duckdb_client", side_effect=RuntimeError):
            result = _load_cross_asset_snapshot()
        assert result == {}


# ─── Q4 Optimizer ────────────────────────────────────────────────────────────

class TestQ4OptimizerLoaders:
    def test_load_optimization_report_returns_dict(self) -> None:
        from presentation.dashboard_engine.pages.Q4_Optimizer import _load_optimization_report
        result = _load_optimization_report()
        assert isinstance(result, dict)


# ─── Q5 Sentiment ────────────────────────────────────────────────────────────

class TestQ5SentimentLoaders:
    def test_load_sentiment_scores_returns_dict(self) -> None:
        from presentation.dashboard_engine.pages.Q5_Sentiment import _load_sentiment_scores
        result = _load_sentiment_scores()
        assert isinstance(result, dict)

    def test_load_sentiment_scores_graceful_on_error(self) -> None:
        from presentation.dashboard_engine.pages.Q5_Sentiment import _load_sentiment_scores
        with patch(
            "engine.analytics.sentiment.live_sentiment_service.get_live_sentiment_service",
            side_effect=RuntimeError,
        ):
            result = _load_sentiment_scores()
        assert result == {}

    def test_load_sentiment_history_returns_dataframe(self) -> None:
        from presentation.dashboard_engine.pages.Q5_Sentiment import _load_sentiment_history
        result = _load_sentiment_history()
        assert isinstance(result, pd.DataFrame)

    def test_load_sentiment_history_empty_on_db_error(self) -> None:
        from presentation.dashboard_engine.pages.Q5_Sentiment import _load_sentiment_history
        with patch("shared.db.duckdb_client.get_duckdb_client", side_effect=RuntimeError):
            result = _load_sentiment_history()
        assert result.empty

    def test_load_sentiment_history_accepts_days_param(self) -> None:
        from presentation.dashboard_engine.pages.Q5_Sentiment import _load_sentiment_history
        result = _load_sentiment_history(days=7)
        assert isinstance(result, pd.DataFrame)

    def test_source_labels_covers_all_expected_keys(self) -> None:
        from presentation.dashboard_engine.pages.Q5_Sentiment import _SOURCE_LABELS
        expected = {"cnn_fg", "crypto_fg", "put_call", "finnhub", "aaii", "cot", "insider", "short_int"}
        assert set(_SOURCE_LABELS.keys()) == expected
