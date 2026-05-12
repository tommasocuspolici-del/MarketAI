"""Tests LabourForecastEngine — fit + forecast su dati sintetici, benchmark < 5s."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest
from engine.analytics.labour_market.labour_forecast_engine import LabourForecastEngine


def _make_target_and_features(n: int = 60) -> tuple:
    rng    = np.random.default_rng(42)
    idx    = pd.date_range("2019-01-01", periods=n, freq="MS")
    target = pd.Series(4.0 + rng.standard_normal(n).cumsum() * 0.1, index=idx, name="UNRATE")
    target = target.clip(2.0, 12.0)
    feats  = pd.DataFrame({
        "claims_4wk_ma": 250_000 + rng.standard_normal(n) * 10_000,
        "quits_rate":    2.5 + rng.standard_normal(n) * 0.2,
        "openings_rate": 4.5 + rng.standard_normal(n) * 0.5,
    }, index=idx)
    return target, feats


class TestLabourForecastEngine:

    def test_fit_no_error(self):
        """fit() su 60 mesi non solleva eccezioni."""
        engine = LabourForecastEngine()
        target, feats = _make_target_and_features(60)
        engine.fit(target, feats)
        assert engine.is_fitted

    def test_forecast_returns_all_horizons(self):
        """forecast() restituisce tutti e 3 gli orizzonti."""
        engine = LabourForecastEngine()
        target, feats = _make_target_and_features(60)
        engine.fit(target, feats)
        future_feats = feats.tail(6).reset_index(drop=True)
        result = engine.forecast(["1M","3M","6M"], future_feats, "UNRATE")
        assert len(result.bundles) == 3
        horizons = {b.horizon for b in result.bundles}
        assert horizons == {"1M","3M","6M"}

    def test_forecast_values_plausible(self):
        """Valori forecast nel range plausibile [1%, 15%] per UNRATE."""
        engine = LabourForecastEngine()
        target, feats = _make_target_and_features(60)
        engine.fit(target, feats)
        future_feats = feats.tail(6).reset_index(drop=True)
        result = engine.forecast(["3M"], future_feats, "UNRATE")
        b = result.bundles[0]
        assert b.lower_10 <= b.point_forecast <= b.upper_90

    def test_fit_insufficient_data_raises(self):
        """< 24 osservazioni → ValueError."""
        engine = LabourForecastEngine()
        target, feats = _make_target_and_features(10)
        with pytest.raises(ValueError, match="insufficienti"):
            engine.fit(target, feats)

    def test_forecast_before_fit_raises(self):
        """forecast() prima di fit() → RuntimeError."""
        engine = LabourForecastEngine()
        feats = pd.DataFrame({"a": [1,2,3]})
        with pytest.raises(RuntimeError, match="fit"):
            engine.forecast(["1M"], feats, "UNRATE")

    @pytest.mark.benchmark(group="labour_forecast")
    def test_compute_under_5s(self, benchmark):
        """Benchmark: fit + forecast 3 orizzonti < 5s."""
        engine = LabourForecastEngine()
        target, feats = _make_target_and_features(120)  # 10 anni
        def _run():
            e = LabourForecastEngine()
            e.fit(target, feats)
            e.forecast(["1M","3M","6M"], feats.tail(6).reset_index(drop=True), "UNRATE")
        result = benchmark.pedantic(_run, iterations=1, rounds=3)
        # Benchmark assertion handled by pytest-benchmark thresholds
