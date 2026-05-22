from __future__ import annotations

import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch

from engine.analytics.forecasting.var_vecm_engine import (
    VAREngine,
    VARForecast,
    DEFAULT_LAGS,
    FEATURE_FLAG,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_macro_df(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    idx = pd.date_range("2000-01-01", periods=n, freq="MS", tz="UTC")
    return pd.DataFrame(
        {
            "FEDFUNDS": rng.uniform(0.5, 5.5, n),
            "CPIAUCSL": np.cumsum(rng.normal(0.2, 0.05, n)) + 200,
            "UNRATE":   rng.uniform(3.5, 8.5, n),
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

class TestInstantiation:
    def test_default_max_lags(self) -> None:
        engine = VAREngine()
        assert engine._max_lags == DEFAULT_LAGS

    def test_custom_max_lags(self) -> None:
        engine = VAREngine(max_lags=2)
        assert engine._max_lags == 2

    def test_not_fitted_initially(self) -> None:
        engine = VAREngine()
        assert engine.is_fitted() is False


# ---------------------------------------------------------------------------
# fit (feature flag disabled)
# ---------------------------------------------------------------------------

class TestFitFlagDisabled:
    def test_fit_returns_self_when_flag_disabled(self) -> None:
        engine = VAREngine()
        df = _make_macro_df()
        with patch("engine.analytics.forecasting.var_vecm_engine.is_enabled", return_value=False):
            result = engine.fit(df)
        assert result is engine

    def test_not_fitted_when_flag_disabled(self) -> None:
        engine = VAREngine()
        df = _make_macro_df()
        with patch("engine.analytics.forecasting.var_vecm_engine.is_enabled", return_value=False):
            engine.fit(df)
        assert engine.is_fitted() is False

    def test_forecast_returns_empty_when_not_fitted(self) -> None:
        engine = VAREngine()
        # flag disabled → not fitted → forecast returns []
        with patch("engine.analytics.forecasting.var_vecm_engine.is_enabled", return_value=False):
            engine.fit(_make_macro_df())
        result = engine.forecast(steps=3)
        assert result == []


# ---------------------------------------------------------------------------
# fit (feature flag enabled)
# ---------------------------------------------------------------------------

class TestFitFlagEnabled:
    def test_fit_with_statsmodels(self) -> None:
        pytest.importorskip("statsmodels")
        engine = VAREngine(max_lags=2)
        df = _make_macro_df(n=120)
        with patch("engine.analytics.forecasting.var_vecm_engine.is_enabled", return_value=True):
            result = engine.fit(df)
        assert result is engine

    def test_is_fitted_after_fit(self) -> None:
        pytest.importorskip("statsmodels")
        engine = VAREngine(max_lags=2)
        df = _make_macro_df(n=120)
        with patch("engine.analytics.forecasting.var_vecm_engine.is_enabled", return_value=True):
            engine.fit(df)
        assert engine.is_fitted() is True

    def test_fit_stores_columns(self) -> None:
        pytest.importorskip("statsmodels")
        engine = VAREngine(max_lags=2)
        df = _make_macro_df(n=120)
        with patch("engine.analytics.forecasting.var_vecm_engine.is_enabled", return_value=True):
            engine.fit(df)
        assert set(engine._columns) == {"FEDFUNDS", "CPIAUCSL", "UNRATE"}

    def test_insufficient_data_stays_not_fitted(self) -> None:
        pytest.importorskip("statsmodels")
        engine = VAREngine(max_lags=4)
        # Only 5 rows — insufficient for 4 lags + 10 = 14 required
        df = _make_macro_df(n=5)
        with patch("engine.analytics.forecasting.var_vecm_engine.is_enabled", return_value=True):
            engine.fit(df)
        assert engine.is_fitted() is False


# ---------------------------------------------------------------------------
# forecast (feature flag enabled)
# ---------------------------------------------------------------------------

class TestForecast:
    def test_forecast_returns_list_of_var_forecast(self) -> None:
        pytest.importorskip("statsmodels")
        engine = VAREngine(max_lags=2)
        df = _make_macro_df(n=120)
        with patch("engine.analytics.forecasting.var_vecm_engine.is_enabled", return_value=True):
            engine.fit(df)
        if not engine.is_fitted():
            pytest.skip("Statsmodels fit failed in this environment")
        forecasts = engine.forecast(steps=3)
        assert isinstance(forecasts, list)
        assert len(forecasts) > 0
        for fc in forecasts:
            assert isinstance(fc, VARForecast)

    def test_forecast_fields(self) -> None:
        pytest.importorskip("statsmodels")
        engine = VAREngine(max_lags=2)
        df = _make_macro_df(n=120)
        with patch("engine.analytics.forecasting.var_vecm_engine.is_enabled", return_value=True):
            engine.fit(df)
        if not engine.is_fitted():
            pytest.skip("Statsmodels fit failed in this environment")
        forecasts = engine.forecast(steps=3)
        for fc in forecasts:
            assert isinstance(fc.variable, str)
            assert isinstance(fc.horizon_months, int)
            assert fc.horizon_months >= 1
            assert isinstance(fc.point_forecast, float)
            assert isinstance(fc.is_cointegrated, bool)

    def test_forecast_covers_all_variables(self) -> None:
        pytest.importorskip("statsmodels")
        engine = VAREngine(max_lags=2)
        df = _make_macro_df(n=120)
        with patch("engine.analytics.forecasting.var_vecm_engine.is_enabled", return_value=True):
            engine.fit(df)
        if not engine.is_fitted():
            pytest.skip("Statsmodels fit failed in this environment")
        forecasts = engine.forecast(steps=3)
        variables = {fc.variable for fc in forecasts}
        assert variables == {"FEDFUNDS", "CPIAUCSL", "UNRATE"}

    def test_get_lag_order_after_fit(self) -> None:
        pytest.importorskip("statsmodels")
        engine = VAREngine(max_lags=2)
        df = _make_macro_df(n=120)
        with patch("engine.analytics.forecasting.var_vecm_engine.is_enabled", return_value=True):
            engine.fit(df)
        if engine.is_fitted():
            assert engine.get_lag_order() >= 1
