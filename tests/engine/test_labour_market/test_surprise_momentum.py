"""Tests SurpriseMomentum — accelerazione/decelerazione sorprese."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.analytics.surprise_engine.surprise_momentum import SurpriseMomentum, MomentumSignal


def _make_history(sector: str, values: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2023-01-01", periods=len(values), freq="MS")
    return pd.DataFrame({
        "sector": sector,
        "snapshot_date": dates,
        "surprise_index": values,
    })


class TestSurpriseMomentumCompute:
    def test_returns_list(self):
        df = _make_history("labour", [0.1, 0.2, 0.3, 0.4])
        result = SurpriseMomentum().compute(df)
        assert isinstance(result, list)

    def test_returns_momentum_signal_objects(self):
        df = _make_history("labour", [0.1, 0.2, 0.3, 0.4])
        result = SurpriseMomentum().compute(df)
        assert len(result) == 1
        assert isinstance(result[0], MomentumSignal)

    def test_multiple_sectors(self):
        df = pd.concat([
            _make_history("labour", [0.1, 0.2, 0.3, 0.4]),
            _make_history("growth", [0.5, 0.4, 0.3, 0.2]),
        ])
        result = SurpriseMomentum().compute(df)
        sectors = {r.sector for r in result}
        assert "labour" in sectors
        assert "growth" in sectors

    def test_positive_momentum_1m_on_rising_series(self):
        # Monotonically rising → last diff is positive
        df = _make_history("labour", [0.1, 0.2, 0.3, 0.4])
        result = SurpriseMomentum().compute(df)
        assert result[0].momentum_1m > 0

    def test_negative_momentum_1m_on_falling_series(self):
        df = _make_history("labour", [0.4, 0.3, 0.2, 0.1])
        result = SurpriseMomentum().compute(df)
        assert result[0].momentum_1m < 0

    def test_accelerating_regime(self):
        # Big jump at end → acceleration positive → regime accelerating
        df = _make_history("labour", [0.0, 0.1, 0.1, 0.6])
        result = SurpriseMomentum().compute(df)
        assert result[0].regime == "accelerating"

    def test_decelerating_regime(self):
        # Big drop at end → acceleration negative → regime decelerating
        df = _make_history("labour", [0.6, 0.5, 0.5, 0.0])
        result = SurpriseMomentum().compute(df)
        assert result[0].regime == "decelerating"

    def test_stable_regime_flat_series(self):
        df = _make_history("labour", [0.3, 0.3, 0.3, 0.3])
        result = SurpriseMomentum().compute(df)
        assert result[0].regime == "stable"

    def test_handles_short_series_two_points(self):
        df = _make_history("labour", [0.1, 0.2])
        result = SurpriseMomentum().compute(df)
        assert len(result) == 1
        assert result[0].momentum_3m == 0.0  # insufficient data fallback

    def test_handles_single_point(self):
        df = _make_history("labour", [0.5])
        result = SurpriseMomentum().compute(df)
        assert len(result) == 1
        assert result[0].momentum_1m == 0.0

    def test_empty_dataframe_returns_empty(self):
        df = pd.DataFrame(columns=["sector", "snapshot_date", "surprise_index"])
        result = SurpriseMomentum().compute(df)
        assert result == []


class TestMomentumSignalSchema:
    def test_fields_rounded_to_4dp(self):
        df = _make_history("growth", [0.123456, 0.234567, 0.345678, 0.456789])
        result = SurpriseMomentum().compute(df)
        sig = result[0]
        # Rounded to 4 decimal places
        assert sig.momentum_1m == round(sig.momentum_1m, 4)
        assert sig.momentum_3m == round(sig.momentum_3m, 4)

    def test_sector_name_preserved(self):
        df = _make_history("inflation", [0.1, 0.2, 0.3, 0.4])
        result = SurpriseMomentum().compute(df)
        assert result[0].sector == "inflation"
