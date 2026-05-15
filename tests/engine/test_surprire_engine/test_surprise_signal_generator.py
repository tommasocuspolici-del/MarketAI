"""Tests for SurpriseSignalGenerator and SectorSurpriseAggregator extra paths."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from engine.analytics.surprise_engine.surprise_engine import (
    SectorSurpriseIndex,
    SurpriseCompositeSignal,
    SurpriseSignalGenerator,
    SectorSurpriseAggregator,
)


def _make_sector(sector: str, index: float, beats: int = 3, misses: int = 1) -> SectorSurpriseIndex:
    return SectorSurpriseIndex(
        sector=sector,
        snapshot_date=date(2024, 1, 5),
        surprise_index=index,
        momentum_1m=0.1,
        momentum_3m=0.2,
        regime="positive_surprise" if index > 0 else "negative_surprise",
        beat_count=beats,
        miss_count=misses,
        data_points=beats + misses,
    )


class TestSurpriseSignalGenerator:
    def test_generate_returns_composite_signal(self):
        gen = SurpriseSignalGenerator()
        indices = [_make_sector("labour", 1.5), _make_sector("growth", 0.5)]
        result = gen.generate(indices)
        assert isinstance(result, SurpriseCompositeSignal)

    def test_signal_in_range(self):
        gen = SurpriseSignalGenerator()
        indices = [_make_sector(s, v) for s, v in [
            ("labour", 2.5), ("growth", 1.0), ("inflation", -0.5), ("housing", 0.8)
        ]]
        result = gen.generate(indices)
        assert -1.0 <= result.signal_value <= 1.0

    def test_signal_positive_on_positive_surprises(self):
        gen = SurpriseSignalGenerator()
        indices = [_make_sector("labour", 2.0), _make_sector("growth", 2.0)]
        result = gen.generate(indices)
        assert result.signal_value > 0

    def test_signal_negative_on_negative_surprises(self):
        gen = SurpriseSignalGenerator()
        indices = [_make_sector("labour", -2.0), _make_sector("growth", -2.0)]
        result = gen.generate(indices)
        assert result.signal_value < 0

    def test_empty_sectors_returns_zero(self):
        gen = SurpriseSignalGenerator()
        result = gen.generate([])
        assert result.signal_value == 0.0
        assert result.dominant_sector == "unknown"

    def test_unknown_sector_ignored(self):
        gen = SurpriseSignalGenerator()
        # "nonexistent_sector" not in _SECTOR_WEIGHTS → should be ignored
        indices = [_make_sector("nonexistent_sector", 3.0)]
        result = gen.generate(indices)
        assert result.signal_value == 0.0

    def test_beat_miss_counts_aggregated(self):
        gen = SurpriseSignalGenerator()
        indices = [
            _make_sector("labour", 1.0, beats=5, misses=2),
            _make_sector("growth", 0.5, beats=3, misses=1),
        ]
        result = gen.generate(indices)
        assert result.beat_count == 8
        assert result.miss_count == 3

    def test_dominant_sector_is_largest_abs(self):
        gen = SurpriseSignalGenerator()
        indices = [
            _make_sector("labour", 0.1),
            _make_sector("growth", 2.9),    # largest absolute
            _make_sector("inflation", -0.5),
        ]
        result = gen.generate(indices)
        assert result.dominant_sector == "growth"

    def test_persist_called_when_duckdb_provided(self):
        db = MagicMock()
        gen = SurpriseSignalGenerator(duckdb=db)
        indices = [_make_sector("labour", 1.0)]
        gen.generate(indices)
        assert db.execute.called

    def test_persist_skipped_when_no_duckdb(self):
        gen = SurpriseSignalGenerator(duckdb=None)
        indices = [_make_sector("labour", 1.0)]
        result = gen.generate(indices)
        assert isinstance(result, SurpriseCompositeSignal)


class TestSectorSurpriseAggregatorExtra:
    """Additional paths not covered by existing tests."""

    def _weights(self) -> dict[str, dict[str, float]]:
        return {
            "labour": {"NFP": 0.5, "CLAIMS": 0.5},
            "growth": {"ISM_MFG": 1.0},
        }

    def test_aggregate_returns_list(self):
        import pandas as pd
        from datetime import date, timedelta
        agg = SectorSurpriseAggregator(indicator_weights=self._weights())
        # Provide several months of data so aggregator has enough history
        today = date.today()
        dates = [today - timedelta(days=30 * i) for i in range(6)]
        df = pd.DataFrame({
            "release_date": pd.to_datetime(dates),
            "indicator_code": ["NFP"] * 6,
            "sector": ["labour"] * 6,
            "surprise_z": [1.5, 0.8, 1.2, 0.5, 1.0, 0.7],
        })
        result = agg.aggregate(df)
        assert isinstance(result, list)

    def test_aggregate_empty_df_returns_empty_list(self):
        import pandas as pd
        agg = SectorSurpriseAggregator(indicator_weights=self._weights())
        df = pd.DataFrame(columns=["release_date", "indicator_code", "sector", "surprise_z"])
        result = agg.aggregate(df)
        assert result == []

    def test_aggregate_with_persist(self):
        import pandas as pd
        db = MagicMock()
        agg = SectorSurpriseAggregator(indicator_weights=self._weights(), duckdb=db)
        df = pd.DataFrame({
            "release_date": pd.to_datetime(["2024-01-05"]),
            "indicator_code": ["NFP"],
            "sector": ["labour"],
            "surprise_z": [1.2],
        })
        result = agg.aggregate(df)
        assert isinstance(result, list)
