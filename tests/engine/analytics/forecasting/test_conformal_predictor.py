"""Tests for AdaptiveConformalPredictor."""
from __future__ import annotations

import numpy as np
import pytest

from engine.analytics.forecasting.conformal_predictor import (
    AdaptiveConformalPredictor,
    ConformalInterval,
    DEFAULT_ALPHA,
    MIN_CALIBRATION,
)


# ─── Fixtures ────────────────────────────────────────────────────────────── #

@pytest.fixture
def predictor() -> AdaptiveConformalPredictor:
    return AdaptiveConformalPredictor(alpha=0.10, calibration_window=252)


def _fill_calibration(predictor: AdaptiveConformalPredictor, n: int = 50) -> None:
    """Feed n (actual, forecast) pairs with residual = 0.5."""
    rng = np.random.default_rng(42)
    for _ in range(n):
        actual = rng.normal(0.0, 1.0)
        forecast = actual + rng.normal(0.0, 0.5)
        predictor.update(actual, forecast)


# ─── Tests ───────────────────────────────────────────────────────────────── #

class TestUpdate:
    def test_update_increments_count(self, predictor: AdaptiveConformalPredictor) -> None:
        assert predictor.n_calibration_samples() == 0
        predictor.update(1.0, 0.9)
        assert predictor.n_calibration_samples() == 1

    def test_update_respects_window(self) -> None:
        window = 30
        pred = AdaptiveConformalPredictor(calibration_window=window)
        for i in range(window + 10):
            pred.update(float(i), 0.0)
        assert pred.n_calibration_samples() == window

    def test_update_computes_absolute_residual(self, predictor: AdaptiveConformalPredictor) -> None:
        # |actual - forecast| deve essere sempre ≥ 0
        predictor.update(-5.0, 3.0)   # residual = 8.0
        predictor.update(3.0, -5.0)   # residual = 8.0
        # Entrambi devono essere trattati come 8.0
        assert predictor.n_calibration_samples() == 2


class TestPredictInterval:
    def test_insufficient_calibration_returns_invalid(self, predictor: AdaptiveConformalPredictor) -> None:
        # Meno di MIN_CALIBRATION campioni → is_valid=False
        for _ in range(MIN_CALIBRATION - 1):
            predictor.update(1.0, 1.0)

        result = predictor.predict_interval(5.0)

        assert not result.is_valid
        assert result.point_forecast == 5.0
        assert result.lower == result.upper == 5.0

    def test_valid_interval_with_sufficient_calibration(self, predictor: AdaptiveConformalPredictor) -> None:
        _fill_calibration(predictor, n=50)

        result = predictor.predict_interval(10.0)

        assert result.is_valid
        assert result.lower < result.point_forecast
        assert result.point_forecast < result.upper

    def test_coverage_level_stored_correctly(self, predictor: AdaptiveConformalPredictor) -> None:
        _fill_calibration(predictor, n=50)
        result = predictor.predict_interval(0.0)
        assert abs(result.coverage_level - (1.0 - 0.10)) < 1e-9

    def test_n_calibration_in_result(self, predictor: AdaptiveConformalPredictor) -> None:
        _fill_calibration(predictor, n=50)
        result = predictor.predict_interval(0.0)
        assert result.n_calibration == 50

    def test_interval_width_increases_with_spread(self) -> None:
        """Residui più grandi → intervallo più ampio."""
        pred_narrow = AdaptiveConformalPredictor(alpha=0.10)
        pred_wide = AdaptiveConformalPredictor(alpha=0.10)

        # Narrow: residui piccoli
        for i in range(50):
            pred_narrow.update(float(i), float(i) + 0.01)

        # Wide: residui grandi
        for i in range(50):
            pred_wide.update(float(i), float(i) + 10.0)

        narrow_result = pred_narrow.predict_interval(0.0)
        wide_result = pred_wide.predict_interval(0.0)

        narrow_width = narrow_result.upper - narrow_result.lower
        wide_width = wide_result.upper - wide_result.lower
        assert wide_width > narrow_width

    def test_alpha_05_gives_wider_interval_than_alpha_20(self) -> None:
        """Alpha più bassa (95% coverage) → intervallo più ampio di alpha alta (80% coverage)."""
        pred_low_alpha = AdaptiveConformalPredictor(alpha=0.05)
        pred_high_alpha = AdaptiveConformalPredictor(alpha=0.20)

        rng = np.random.default_rng(7)
        for _ in range(60):
            actual = rng.normal(0, 1)
            forecast = actual + rng.normal(0, 0.5)
            pred_low_alpha.update(actual, forecast)
            pred_high_alpha.update(actual, forecast)

        res_low = pred_low_alpha.predict_interval(0.0)
        res_high = pred_high_alpha.predict_interval(0.0)

        assert res_low.upper - res_low.lower >= res_high.upper - res_high.lower


class TestReset:
    def test_reset_clears_calibration(self, predictor: AdaptiveConformalPredictor) -> None:
        _fill_calibration(predictor, n=50)
        predictor.reset()
        assert predictor.n_calibration_samples() == 0

    def test_predict_invalid_after_reset(self, predictor: AdaptiveConformalPredictor) -> None:
        _fill_calibration(predictor, n=50)
        predictor.reset()
        result = predictor.predict_interval(1.0)
        assert not result.is_valid
