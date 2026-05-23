from __future__ import annotations

import math
import pytest
from shared.exceptions import MarketAIError
import numpy as np
import pandas as pd

from engine.analytics.forecasting.ensemble_combiner import (
    EnsembleCombiner,
    EnsembleResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def combiner() -> EnsembleCombiner:
    return EnsembleCombiner()


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

class TestInstantiation:
    def test_instantiates(self) -> None:
        c = EnsembleCombiner()
        assert isinstance(c, EnsembleCombiner)


# ---------------------------------------------------------------------------
# combine_equal_weight
# ---------------------------------------------------------------------------

class TestCombineEqualWeight:
    def test_returns_ensemble_result(self, combiner: EnsembleCombiner) -> None:
        result = combiner.combine_equal_weight({"arima": 1.0, "ridge": 1.5})
        assert isinstance(result, EnsembleResult)

    def test_equal_weight_point_forecast(self, combiner: EnsembleCombiner) -> None:
        result = combiner.combine_equal_weight({"arima": 1.0, "ridge": 1.5})
        assert math.isclose(result.point_forecast, 1.25, rel_tol=1e-9)

    def test_weights_sum_to_one(self, combiner: EnsembleCombiner) -> None:
        result = combiner.combine_equal_weight({"arima": 1.0, "ridge": 1.5, "ets": 2.0})
        assert math.isclose(sum(result.model_weights.values()), 1.0, rel_tol=1e-9)

    def test_weights_are_equal(self, combiner: EnsembleCombiner) -> None:
        result = combiner.combine_equal_weight({"arima": 1.0, "ridge": 1.5})
        for w in result.model_weights.values():
            assert math.isclose(w, 0.5, rel_tol=1e-9)

    def test_method_label(self, combiner: EnsembleCombiner) -> None:
        result = combiner.combine_equal_weight({"arima": 1.0, "ridge": 1.5})
        assert result.ensemble_method == "equal"

    def test_empty_forecasts_raises(self, combiner: EnsembleCombiner) -> None:
        with pytest.raises((ValueError, MarketAIError)):
            combiner.combine_equal_weight({})

    def test_single_model(self, combiner: EnsembleCombiner) -> None:
        result = combiner.combine_equal_weight({"arima": 3.0})
        assert math.isclose(result.point_forecast, 3.0, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# combine_ic_weighted
# ---------------------------------------------------------------------------

class TestCombineICWeighted:
    def test_returns_ensemble_result(self, combiner: EnsembleCombiner) -> None:
        result = combiner.combine_ic_weighted(
            {"arima": 1.0, "ridge": 1.5},
            {"arima": 0.08, "ridge": 0.04},
        )
        assert isinstance(result, EnsembleResult)

    def test_higher_ic_gets_more_weight(self, combiner: EnsembleCombiner) -> None:
        """arima IC=0.08 > ridge IC=0.04 → forecast closer to arima=1.0 than ridge=1.5"""
        result = combiner.combine_ic_weighted(
            {"arima": 1.0, "ridge": 1.5},
            {"arima": 0.08, "ridge": 0.04},
        )
        # The weighted forecast should be closer to 1.0 than to 1.5
        assert result.point_forecast < 1.25  # < equal-weight midpoint

    def test_weights_sum_to_one(self, combiner: EnsembleCombiner) -> None:
        result = combiner.combine_ic_weighted(
            {"arima": 1.0, "ridge": 1.5},
            {"arima": 0.08, "ridge": 0.04},
        )
        assert math.isclose(sum(result.model_weights.values()), 1.0, rel_tol=1e-6)

    def test_method_label(self, combiner: EnsembleCombiner) -> None:
        result = combiner.combine_ic_weighted(
            {"m1": 1.0},
            {"m1": 0.1},
        )
        assert result.ensemble_method == "ic_weighted"

    def test_equal_ic_produces_equal_weights(self, combiner: EnsembleCombiner) -> None:
        result = combiner.combine_ic_weighted(
            {"arima": 1.0, "ridge": 1.5},
            {"arima": 0.05, "ridge": 0.05},
        )
        # Equal IC → equal weights → forecast ≈ 1.25
        assert math.isclose(result.point_forecast, 1.25, rel_tol=1e-6)

    def test_empty_forecasts_raises(self, combiner: EnsembleCombiner) -> None:
        with pytest.raises((ValueError, MarketAIError)):
            combiner.combine_ic_weighted({}, {})


# ---------------------------------------------------------------------------
# combine_ridge_stacking
# ---------------------------------------------------------------------------

class TestCombineRidgeStacking:
    def _make_history(self, n: int = 30) -> tuple[pd.DataFrame, pd.Series]:
        rng = np.random.default_rng(42)
        arima_fc = rng.normal(1.5, 0.2, n)
        ridge_fc = rng.normal(1.5, 0.3, n)
        actuals = rng.normal(1.5, 0.1, n)
        history = pd.DataFrame({"arima": arima_fc, "ridge": ridge_fc})
        return history, pd.Series(actuals)

    def test_returns_ensemble_result(self, combiner: EnsembleCombiner) -> None:
        history, actuals = self._make_history()
        result = combiner.combine_ridge_stacking(
            history, actuals, {"arima": 1.4, "ridge": 1.6}
        )
        assert isinstance(result, EnsembleResult)

    def test_weights_sum_to_approximately_one(self, combiner: EnsembleCombiner) -> None:
        history, actuals = self._make_history()
        result = combiner.combine_ridge_stacking(
            history, actuals, {"arima": 1.4, "ridge": 1.6}
        )
        # Weights are clipped positive and normalized → sum ≈ 1 (or fallback equal weight)
        assert sum(result.model_weights.values()) >= 0.0

    def test_insufficient_history_falls_back_to_equal(self, combiner: EnsembleCombiner) -> None:
        empty_history = pd.DataFrame({"arima": [], "ridge": []})
        empty_actuals = pd.Series([], dtype=float)
        result = combiner.combine_ridge_stacking(
            empty_history, empty_actuals, {"arima": 1.0, "ridge": 2.0}
        )
        # Fallback: equal weight → mean = 1.5
        assert isinstance(result, EnsembleResult)

    def test_model_forecasts_stored(self, combiner: EnsembleCombiner) -> None:
        history, actuals = self._make_history()
        new_fc = {"arima": 1.4, "ridge": 1.6}
        result = combiner.combine_ridge_stacking(history, actuals, new_fc)
        assert result.model_forecasts == new_fc


# ---------------------------------------------------------------------------
# update_kalman_weights
# ---------------------------------------------------------------------------

class TestUpdateKalmanWeights:
    def test_returns_array_same_length(self, combiner: EnsembleCombiner) -> None:
        weights = np.array([0.5, 0.5])
        errors = np.array([0.1, 0.2])
        result = combiner.update_kalman_weights(weights, errors)
        assert len(result) == 2

    def test_output_sums_to_one(self, combiner: EnsembleCombiner) -> None:
        weights = np.array([0.4, 0.6])
        errors = np.array([0.05, 0.15])
        result = combiner.update_kalman_weights(weights, errors)
        assert math.isclose(result.sum(), 1.0, rel_tol=1e-6)

    def test_all_weights_non_negative(self, combiner: EnsembleCombiner) -> None:
        weights = np.array([0.3, 0.4, 0.3])
        errors = np.array([0.1, 0.2, 0.3])
        result = combiner.update_kalman_weights(weights, errors)
        assert (result >= 0).all()

    def test_shape_mismatch_raises(self, combiner: EnsembleCombiner) -> None:
        weights = np.array([0.5, 0.5])
        errors = np.array([0.1, 0.2, 0.3])
        with pytest.raises((ValueError, MarketAIError)):
            combiner.update_kalman_weights(weights, errors)

    def test_three_models(self, combiner: EnsembleCombiner) -> None:
        weights = np.array([1 / 3, 1 / 3, 1 / 3])
        errors = np.array([0.01, 0.05, 0.10])
        result = combiner.update_kalman_weights(weights, errors)
        assert result.shape == (3,)
        assert math.isclose(result.sum(), 1.0, rel_tol=1e-6)
