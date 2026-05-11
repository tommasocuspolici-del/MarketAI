"""Tests for engine.market_data.cleaning.gap_filler."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.market_data.cleaning.gap_filler import (
    count_gaps_business_days,
    forward_fill_short_gaps,
)


class TestCountGapsBusinessDays:
    def test_continuous_business_days_no_gaps(self) -> None:
        # 10 giorni lavorativi consecutivi: 0 gap
        ts = pd.date_range(start="2025-01-06", periods=10, freq="B", tz="UTC")
        assert count_gaps_business_days(pd.Series(ts)) == 0

    def test_skipping_one_business_day(self) -> None:
        # Skip un mercoledì: deve essere flaggato come gap
        ts_list = pd.to_datetime(
            ["2025-01-06", "2025-01-07", "2025-01-09", "2025-01-10"], utc=True
        )
        gaps = count_gaps_business_days(pd.Series(ts_list))
        assert gaps == 1  # manca l'8 gennaio (mercoledì)

    def test_weekends_not_counted_as_gaps(self) -> None:
        # Lun-mar-mer-gio-ven: weekend successivo non è un gap
        ts = pd.date_range(start="2025-01-06", periods=5, freq="B", tz="UTC")
        assert count_gaps_business_days(pd.Series(ts)) == 0

    def test_empty_or_single_returns_zero(self) -> None:
        assert count_gaps_business_days(pd.Series([], dtype="datetime64[ns, UTC]")) == 0
        single = pd.Series([pd.Timestamp("2025-01-06", tz="UTC")])
        assert count_gaps_business_days(single) == 0


class TestForwardFillShortGaps:
    def _make_df(self, values: list[float | None]) -> pd.DataFrame:
        ts = pd.date_range(start="2025-01-01", periods=len(values), freq="D", tz="UTC")
        return pd.DataFrame({"ts": ts, "close": [np.nan if v is None else v for v in values]})

    def test_fills_short_gap(self) -> None:
        df = self._make_df([100.0, None, None, 105.0, 110.0])
        filled, n = forward_fill_short_gaps(df, ts_col="ts", max_gap_days=7, columns=["close"])
        assert n == 2
        # Posizioni 1 e 2 devono ereditare il valore 100.0
        assert filled["close"].iloc[1] == 100.0
        assert filled["close"].iloc[2] == 100.0

    def test_does_not_fill_long_gap(self) -> None:
        # Gap di 10 giorni > max_gap_days=7 → NON deve riempire
        # Inseriamo un NaN il 12-01: distanza dal prev (01-01) = 11 giorni > 7
        df = pd.DataFrame(
            {
                "ts": [
                    pd.Timestamp("2025-01-01", tz="UTC"),
                    pd.Timestamp("2025-01-12", tz="UTC"),
                    pd.Timestamp("2025-01-15", tz="UTC"),
                ],
                "close": [100.0, np.nan, 105.0],
            }
        )
        filled, _n = forward_fill_short_gaps(df, ts_col="ts", max_gap_days=7, columns=["close"])
        # Il NaN intermedio deve restare NaN (gap > 7 giorni dal prev)
        assert pd.isna(filled["close"].iloc[1])

    def test_no_nans_no_op(self) -> None:
        df = self._make_df([1.0, 2.0, 3.0, 4.0])
        filled, n = forward_fill_short_gaps(df, ts_col="ts", columns=["close"])
        assert n == 0
        assert filled["close"].tolist() == [1.0, 2.0, 3.0, 4.0]

    def test_empty_dataframe(self) -> None:
        df = pd.DataFrame({"ts": [], "close": []})
        filled, n = forward_fill_short_gaps(df, ts_col="ts")
        assert n == 0
        assert filled.empty

    def test_only_processes_specified_columns(self) -> None:
        ts = pd.date_range(start="2025-01-01", periods=3, freq="D", tz="UTC")
        df = pd.DataFrame(
            {"ts": ts, "close": [1.0, np.nan, 3.0], "volume": [100, np.nan, 300]}
        )
        # Solo close → volume resta NaN
        filled, _n = forward_fill_short_gaps(df, ts_col="ts", columns=["close"])
        assert filled["close"].iloc[1] == 1.0
        assert pd.isna(filled["volume"].iloc[1])


@pytest.fixture
def daily_ts() -> pd.Series:
    """Helper fixture: 30 trading days starting 2025-01-06."""
    return pd.Series(pd.date_range(start="2025-01-06", periods=30, freq="B", tz="UTC"))
