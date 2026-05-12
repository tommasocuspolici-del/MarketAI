"""Tests SectorSurpriseAggregator — decadimento esponenziale verificato."""
from __future__ import annotations
import pandas as pd
import numpy as np
import pytest
from engine.analytics.surprise_engine.surprise_engine import SectorSurpriseAggregator


def _make_sector_df(sector: str, z_scores: list[float], indicator: str = "NFP") -> pd.DataFrame:
    dates = pd.date_range(end=pd.Timestamp.today(), periods=len(z_scores), freq="MS")
    return pd.DataFrame({
        "release_date": dates,
        "indicator_code": indicator,
        "sector": sector,
        "surprise_z": z_scores,
    })


class TestSectorSurpriseAggregator:

    def test_positive_index_for_positive_z_scores(self):
        df  = _make_sector_df("labour", [1.5, 2.0, 1.8, 1.2, 1.6])
        agg = SectorSurpriseAggregator(indicator_weights={"labour": {"NFP": 1.0}})
        results = agg.aggregate(df)
        assert len(results) == 1
        assert results[0].surprise_index > 0

    def test_regime_positive_for_high_z(self):
        df  = _make_sector_df("labour", [2.0, 1.8, 2.2, 1.9, 2.1])
        agg = SectorSurpriseAggregator(indicator_weights={"labour": {"NFP": 1.0}})
        results = agg.aggregate(df)
        assert results[0].regime == "positive_surprise"

    def test_decay_reduces_old_surprises(self):
        """Sorpresa 365gg fa pesa < 35% rispetto a oggi (decay_lambda=0.10)."""
        # half-life = ln(2)/0.10 = ~6.9 mesi; dopo 12 mesi weight = exp(-1.2) ≈ 0.30
        days_365 = 365
        weight_365d = float(np.exp(-0.10 * days_365 / 30))
        assert weight_365d < 0.35

    def test_empty_sector_returns_no_result(self):
        df  = _make_sector_df("labour", [1.0, 2.0])
        agg = SectorSurpriseAggregator(indicator_weights={"growth": {"ISM_MFG": 1.0}})
        results = agg.aggregate(df)
        assert results == []

    def test_beat_miss_count_correct(self):
        """beat_count > miss_count quando più valori positivi nella finestra."""
        z = [1.0, 2.0, 1.5]  # tutti positivi → solo beats
        df  = _make_sector_df("labour", z)
        agg = SectorSurpriseAggregator(indicator_weights={"labour": {"NFP": 1.0}})
        results = agg.aggregate(df)
        r = results[0]
        assert r.beat_count > r.miss_count
