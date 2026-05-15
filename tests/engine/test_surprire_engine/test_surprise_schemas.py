"""Tests for surprise engine schemas — SurpriseOutputSchema, IndicatorSurprise."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from engine.analytics.surprise_engine.schemas import (
    IndicatorSurprise,
    SurpriseOutputSchema,
)


class TestIndicatorSurprise:
    def test_instantiation(self):
        s = IndicatorSurprise(
            indicator_code="NFP",
            sector="labour",
            release_date=date(2024, 1, 5),
            surprise_raw=50.0,
            surprise_z=1.5,
            beat=True,
            significant=True,
        )
        assert s.indicator_code == "NFP"
        assert s.beat is True

    def test_negative_z_beat_false(self):
        s = IndicatorSurprise(
            indicator_code="CPI",
            sector="inflation",
            release_date=date(2024, 2, 1),
            surprise_raw=-0.1,
            surprise_z=-1.2,
            beat=False,
            significant=True,
        )
        assert s.beat is False
        assert s.surprise_z < 0

    def test_frozen_immutable(self):
        s = IndicatorSurprise(
            indicator_code="ISM",
            sector="growth",
            release_date=date(2024, 3, 1),
            surprise_raw=2.0,
            surprise_z=0.5,
            beat=True,
            significant=False,
        )
        with pytest.raises((AttributeError, TypeError)):
            s.surprise_z = 99.0  # type: ignore[misc]


class TestSurpriseOutputSchema:
    def _make_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "release_date":   [pd.Timestamp("2024-01-05")],
            "indicator_code": ["NFP"],
            "sector":         ["labour"],
            "consensus":      [180.0],
            "actual":         [230.0],
            "surprise_raw":   [50.0],
            "surprise_std":   [40.0],
            "surprise_z":     [1.25],
        })

    def test_valid_df_passes(self):
        df = self._make_df()
        validated = SurpriseOutputSchema.validate(df)
        assert len(validated) == 1

    def test_extra_columns_allowed(self):
        df = self._make_df()
        df["extra_col"] = "unused"
        validated = SurpriseOutputSchema.validate(df)
        assert "indicator_code" in validated.columns

    def test_nullable_fields_accept_nan(self):
        df = self._make_df()
        df["surprise_raw"] = None
        validated = SurpriseOutputSchema.validate(df)
        assert validated is not None
