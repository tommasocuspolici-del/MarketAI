"""Tests SurpriseCalculator — z-score normalizzato, decadimento esponenziale."""
from __future__ import annotations
import pandas as pd
import numpy as np
import pytest
from engine.analytics.surprise_engine.surprise_engine import SurpriseCalculator


def _make_consensus_df(actual: list[float], consensus: list[float],
                        code: str = "NFP", sector: str = "labour") -> pd.DataFrame:
    dates = pd.date_range("2023-01-01", periods=len(actual), freq="MS")
    return pd.DataFrame({
        "release_date": dates,
        "indicator_code": code,
        "sector": sector,
        "actual": actual,
        "consensus": consensus,
        "prior": actual[:-1] + [actual[-2]],
        "source": "manual",
    })


class TestSurpriseCalculator:

    def test_zscore_zero_when_consensus_equals_actual(self):
        """z=0 quando consensus == actual."""
        vals = [200.0] * 20
        df   = _make_consensus_df(vals, vals)
        calc = SurpriseCalculator()
        result = calc.compute_from_df(df)
        assert abs(result["surprise_z"].iloc[-1]) < 1e-6

    def test_zscore_positive_when_beat(self):
        """z > 0 quando actual > consensus (beat)."""
        actual    = [200.0] * 15 + [250.0]
        consensus = [200.0] * 16
        df   = _make_consensus_df(actual, consensus)
        calc = SurpriseCalculator()
        result = calc.compute_from_df(df)
        assert result["surprise_z"].iloc[-1] > 0

    def test_zscore_negative_when_miss(self):
        """z < 0 quando actual < consensus (miss)."""
        actual    = [200.0] * 15 + [150.0]
        consensus = [200.0] * 16
        df   = _make_consensus_df(actual, consensus)
        calc = SurpriseCalculator()
        result = calc.compute_from_df(df)
        assert result["surprise_z"].iloc[-1] < 0

    def test_zscore_positive_for_large_beat(self):
        """Sorpresa significativa → z > 1.5 (beat forte)."""
        # Alternare piccole sorprese poi una grande: std piccola → z alto
        base_actual   = [200 + (i % 3) * 2 for i in range(20)]  # oscillazione ±2
        base_cons     = [200.0] * 20
        actual = base_actual + [200 + 30]  # sorpresa grande +30
        cons   = base_cons + [200.0]
        df     = _make_consensus_df(actual, cons)
        calc   = SurpriseCalculator()
        result = calc.compute_from_df(df)
        z = result["surprise_z"].iloc[-1]
        assert z > 1.5  # Grande beat → z elevato

    def test_latest_surprises_sorted_by_z_desc(self):
        """get_latest_surprises() ritorna ordinato per |z| decrescente."""
        df1 = _make_consensus_df([100]*12 + [120], [100]*13, "NFP", "labour")
        df2 = _make_consensus_df([50]*12 + [48], [50]*13, "CPI", "inflation")
        df  = pd.concat([df1, df2], ignore_index=True)
        calc = SurpriseCalculator()
        result = calc.compute_from_df(df)
        surprises = calc.get_latest_surprises(result)
        assert surprises[0].indicator_code == "NFP"

    def test_output_columns_present(self):
        """DataFrame output ha colonne surprise_raw, surprise_std, surprise_z."""
        df   = _make_consensus_df([200.0]*12, [200.0]*12)
        calc = SurpriseCalculator()
        out  = calc.compute_from_df(df)
        for col in ["surprise_raw", "surprise_std", "surprise_z"]:
            assert col in out.columns
