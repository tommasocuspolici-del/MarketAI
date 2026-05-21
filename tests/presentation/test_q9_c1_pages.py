"""Tests for Q11, Q12, Q14, C1 pure loader functions — no Streamlit dependency."""
from __future__ import annotations

import pandas as pd
from unittest.mock import MagicMock, patch


# ─── Q11 Options ─────────────────────────────────────────────────────────────

class TestQ11OptionsLoaders:
    def test_load_options_chain_returns_list(self) -> None:
        from presentation.dashboard_engine.pages.Q11_Options import _load_options_chain
        result = _load_options_chain("SPY")
        assert isinstance(result, list)

    def test_load_options_chain_empty_on_db_error(self) -> None:
        from presentation.dashboard_engine.pages.Q11_Options import _load_options_chain
        with patch("shared.db.duckdb_client.get_duckdb_client", side_effect=RuntimeError):
            result = _load_options_chain("SPY")
        assert result == []

    def test_load_vol_surface_returns_dataframe(self) -> None:
        from presentation.dashboard_engine.pages.Q11_Options import _load_vol_surface
        result = _load_vol_surface("SPY")
        assert isinstance(result, pd.DataFrame)

    def test_load_vol_surface_empty_on_db_error(self) -> None:
        from presentation.dashboard_engine.pages.Q11_Options import _load_vol_surface
        with patch("shared.db.duckdb_client.get_duckdb_client", side_effect=RuntimeError):
            result = _load_vol_surface("SPY")
        assert result.empty

    def test_demo_greeks_have_required_keys(self) -> None:
        from presentation.dashboard_engine.pages.Q11_Options import _DEMO_GREEKS
        for row in _DEMO_GREEKS:
            assert "Strike" in row
            assert "Delta" in row
            assert "IV %" in row


# ─── Q12 Multi-Timeframe ─────────────────────────────────────────────────────

class TestQ12MtfLoaders:
    def test_load_mtf_signal_returns_dict(self) -> None:
        from presentation.dashboard_engine.pages.Q12_MultiTimeframe import _load_mtf_signal
        result = _load_mtf_signal("SPY")
        assert isinstance(result, dict)

    def test_load_mtf_signal_empty_on_db_error(self) -> None:
        from presentation.dashboard_engine.pages.Q12_MultiTimeframe import _load_mtf_signal
        with patch("shared.db.duckdb_client.get_duckdb_client", side_effect=RuntimeError):
            result = _load_mtf_signal("SPY")
        assert result == {}

    def test_load_mtf_signal_empty_on_analyzer_error(self) -> None:
        from presentation.dashboard_engine.pages.Q12_MultiTimeframe import _load_mtf_signal
        with patch(
            "engine.analytics.technical.multi_timeframe_analyzer.MultiTimeframeAnalyzer",
            side_effect=RuntimeError,
        ):
            result = _load_mtf_signal("SPY")
        assert result == {}

    def test_load_mtf_history_returns_dataframe(self) -> None:
        from presentation.dashboard_engine.pages.Q12_MultiTimeframe import _load_mtf_history
        result = _load_mtf_history("SPY")
        assert isinstance(result, pd.DataFrame)

    def test_load_mtf_history_empty_on_db_error(self) -> None:
        from presentation.dashboard_engine.pages.Q12_MultiTimeframe import _load_mtf_history
        with patch("shared.db.duckdb_client.get_duckdb_client", side_effect=RuntimeError):
            result = _load_mtf_history("SPY")
        assert result.empty

    def test_timeframe_labels_has_three_keys(self) -> None:
        from presentation.dashboard_engine.pages.Q12_MultiTimeframe import _TIMEFRAME_LABELS
        assert set(_TIMEFRAME_LABELS.keys()) == {"daily", "weekly", "monthly"}


# ─── Q14 Strategy Lab ────────────────────────────────────────────────────────

class TestQ14StrategyLabLoaders:
    def test_load_wf_history_returns_dataframe(self) -> None:
        from presentation.dashboard_engine.pages.Q14_Strategy_Lab import _load_wf_history
        result = _load_wf_history()
        assert isinstance(result, pd.DataFrame)

    def test_load_wf_history_empty_on_runner_error(self) -> None:
        from presentation.dashboard_engine.pages.Q14_Strategy_Lab import _load_wf_history
        with patch("engine.backtesting.backtest_runner.get_backtest_runner", side_effect=RuntimeError):
            result = _load_wf_history()
        assert result.empty

    def test_load_wf_history_limit_param(self) -> None:
        from presentation.dashboard_engine.pages.Q14_Strategy_Lab import _load_wf_history
        result = _load_wf_history(limit=5)
        assert isinstance(result, pd.DataFrame)

    def test_wf_splits_to_df_structure(self) -> None:
        from presentation.dashboard_engine.pages.Q14_Strategy_Lab import _wf_splits_to_df

        mock_perf = MagicMock()
        mock_perf.total_return = 0.15
        mock_perf.sharpe_ratio = 1.2
        mock_perf.max_drawdown = 0.08
        mock_perf.win_rate = 0.55

        mock_split = MagicMock()
        mock_split.performance = mock_perf
        mock_split.ticker = "SPY"
        mock_split.n_trades = 42

        mock_wf = MagicMock()
        mock_wf.split_results = [mock_split, mock_split]

        df = _wf_splits_to_df(mock_wf)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert "Split" in df.columns
        assert "Sharpe" in df.columns

    def test_strategies_list_not_empty(self) -> None:
        from presentation.dashboard_engine.pages.Q14_Strategy_Lab import _STRATEGIES
        assert len(_STRATEGIES) >= 4


# ─── C1 Custom Indicators ────────────────────────────────────────────────────

class TestC1CustomIndicatorsLoaders:
    def test_load_indicator_list_returns_list(self) -> None:
        from presentation.dashboard_engine.pages.C1_Custom_Indicators import _load_indicator_list
        result = _load_indicator_list()
        assert isinstance(result, list)

    def test_load_indicator_list_graceful_on_error(self) -> None:
        from presentation.dashboard_engine.pages.C1_Custom_Indicators import _load_indicator_list
        with patch("custom_indicators.registry.get_indicator_registry", side_effect=RuntimeError):
            result = _load_indicator_list()
        assert result == []

    def test_load_indicator_list_items_have_required_keys(self) -> None:
        from presentation.dashboard_engine.pages.C1_Custom_Indicators import _load_indicator_list
        for item in _load_indicator_list():
            assert "id" in item
            assert "name" in item
            assert "active" in item
            assert "type" in item

    def test_load_ic_scores_returns_dict(self) -> None:
        from presentation.dashboard_engine.pages.C1_Custom_Indicators import _load_ic_scores
        result = _load_ic_scores()
        assert isinstance(result, dict)

    def test_load_ic_scores_graceful_on_error(self) -> None:
        from presentation.dashboard_engine.pages.C1_Custom_Indicators import _load_ic_scores
        with patch("shared.alpha_decay_monitor.AlphaDecayMonitor", side_effect=RuntimeError):
            result = _load_ic_scores()
        assert result == {}

    def test_validate_dsl_expression_valid(self) -> None:
        from presentation.dashboard_engine.pages.C1_Custom_Indicators import _validate_dsl_expression
        ok, msg = _validate_dsl_expression("vix > 25")
        assert isinstance(ok, bool)
        assert isinstance(msg, str)

    def test_validate_dsl_expression_returns_tuple(self) -> None:
        from presentation.dashboard_engine.pages.C1_Custom_Indicators import _validate_dsl_expression
        result = _validate_dsl_expression("1 + 1")
        assert isinstance(result, tuple)
        assert len(result) == 2
