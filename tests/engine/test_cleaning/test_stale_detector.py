"""Tests for engine.market_data.cleaning.stale_detector."""
from __future__ import annotations

import pandas as pd

from engine.market_data.cleaning.stale_detector import (
    count_consecutive_repeats,
    count_stale_days,
)


class TestCountStaleDays:
    def test_recent_data_zero_stale(self) -> None:
        ref = pd.Timestamp("2025-04-15", tz="UTC")
        ts = pd.Series(pd.date_range(end=ref, periods=10, freq="D", tz="UTC"))
        assert count_stale_days(ts, reference=ref) == 0

    def test_old_data_counted(self) -> None:
        ref = pd.Timestamp("2025-04-15", tz="UTC")
        # Ultimo dato 7 giorni fa
        ts = pd.Series([pd.Timestamp("2025-04-08", tz="UTC")])
        assert count_stale_days(ts, reference=ref) == 7

    def test_future_data_returns_zero(self) -> None:
        # Clock skew o errore feed: ts > ref → 0 stale
        ref = pd.Timestamp("2025-04-15", tz="UTC")
        ts = pd.Series([pd.Timestamp("2025-04-20", tz="UTC")])
        assert count_stale_days(ts, reference=ref) == 0

    def test_empty_returns_zero(self) -> None:
        ts = pd.Series([], dtype="datetime64[ns, UTC]")
        assert count_stale_days(ts) == 0


class TestCountConsecutiveRepeats:
    def test_no_repeats_returns_zero(self) -> None:
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        assert count_consecutive_repeats(s, max_consecutive=3) == 0

    def test_short_run_under_threshold(self) -> None:
        # Run di 3 valori uguali, soglia=5 → non stale
        s = pd.Series([1.0, 5.0, 5.0, 5.0, 6.0])
        assert count_consecutive_repeats(s, max_consecutive=5) == 0

    def test_long_run_over_threshold(self) -> None:
        # Run di 8 valori uguali, soglia=5 → 7 sono stale
        # (il primo del run è valido, gli altri 7 sono stuck)
        s = pd.Series([1.0] + [5.0] * 8 + [6.0])
        n = count_consecutive_repeats(s, max_consecutive=5)
        assert n == 7

    def test_short_series_returns_zero(self) -> None:
        s = pd.Series([1.0, 1.0, 1.0])
        assert count_consecutive_repeats(s, max_consecutive=5) == 0

    def test_multiple_runs_summed(self) -> None:
        # Due run separati, ognuno > soglia
        s = pd.Series([1.0] * 7 + [2.0] + [3.0] * 7)
        n = count_consecutive_repeats(s, max_consecutive=5)
        # 7-1 + 7-1 = 12
        assert n == 12
