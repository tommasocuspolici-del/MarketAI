"""Extra coverage tests for ClaimsCycleDetector._compute_signal and _persist paths."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from engine.analytics.labour_market.claims_cycle_detector import (
    ClaimsCycleDetector,
    ClaimsCycleSignal,
)
from engine.market_data.fred_simple_client import FredSimpleClient, FredKeyMissingError


def _make_claims_df(values: list[float], start: str = "2022-01-01") -> pd.DataFrame:
    dates = pd.date_range(start, periods=len(values), freq="W-SAT")
    return pd.DataFrame({"ts": dates, "value": values})


class TestClassifyRegime:
    """Direct tests for _classify_regime static method."""

    def test_contraction_high_yoy(self):
        ma_hist = np.array([300_000.0] * 10)
        regime = ClaimsCycleDetector._classify_regime(
            310_000.0, ma_hist, yoy_pct=20.0, mom_pct=2.0
        )
        assert regime == "contraction"

    def test_contraction_high_mom(self):
        ma_hist = np.array([250_000.0] * 10)
        regime = ClaimsCycleDetector._classify_regime(
            270_000.0, ma_hist, yoy_pct=5.0, mom_pct=10.0
        )
        assert regime == "contraction"

    def test_peak_moderate_mom(self):
        ma_hist = np.array([220_000.0] * 10)
        regime = ClaimsCycleDetector._classify_regime(
            230_000.0, ma_hist, yoy_pct=3.0, mom_pct=6.0
        )
        assert regime == "peak"

    def test_trough_ma_declining(self):
        # Current MA significantly below recent 8-week mean
        ma_hist = np.array([350_000.0] * 6 + [320_000.0, 310_000.0])
        regime = ClaimsCycleDetector._classify_regime(
            300_000.0, ma_hist, yoy_pct=None, mom_pct=None
        )
        assert regime == "trough"

    def test_expansion_default(self):
        ma_hist = np.array([220_000.0] * 10)
        regime = ClaimsCycleDetector._classify_regime(
            220_000.0, ma_hist, yoy_pct=2.0, mom_pct=1.0
        )
        assert regime == "expansion"

    def test_none_yoy_and_mom_falls_to_expansion(self):
        ma_hist = np.array([220_000.0] * 10)
        regime = ClaimsCycleDetector._classify_regime(
            220_000.0, ma_hist, yoy_pct=None, mom_pct=None
        )
        assert regime in ("expansion", "trough")


class TestDetectWithMockFred:
    def _detector(self, db=None, n_weeks: int = 60) -> ClaimsCycleDetector:
        d = ClaimsCycleDetector(duckdb=db)
        vals = [220_000.0 + i * 100 for i in range(n_weeks)]
        df = _make_claims_df(vals)
        d._client = MagicMock(spec=FredSimpleClient)
        d._client.fetch_series.return_value = df
        return d

    def test_detect_calls_persist_when_db(self):
        db = MagicMock()
        d = self._detector(db=db, n_weeks=60)
        result = d.detect()
        assert isinstance(result, ClaimsCycleSignal)
        assert db.execute.called

    def test_detect_no_persist_without_db(self):
        d = self._detector(db=None, n_weeks=60)
        result = d.detect()
        assert isinstance(result, ClaimsCycleSignal)

    def test_detect_raises_on_key_missing(self):
        d = ClaimsCycleDetector(duckdb=None)
        d._client = MagicMock(spec=FredSimpleClient)
        d._client.fetch_series.side_effect = FredKeyMissingError("no key")
        with pytest.raises(FredKeyMissingError):
            d.detect()

    def test_detect_raises_on_insufficient_data(self):
        d = ClaimsCycleDetector(duckdb=None)
        d._client = MagicMock(spec=FredSimpleClient)
        d._client.fetch_series.return_value = _make_claims_df([220_000.0, 221_000.0])
        with pytest.raises(ValueError, match="insufficienti"):
            d.detect()

    def test_signal_in_range(self):
        d = self._detector(n_weeks=60)
        result = d.detect()
        assert -1.0 <= result.signal_strength <= 1.0

    def test_yoy_computed_with_52_weeks(self):
        d = self._detector(n_weeks=60)
        result = d.detect()
        assert result.claims_yoy_pct is not None

    def test_yoy_none_with_short_series(self):
        d = self._detector(n_weeks=20)
        result = d.detect()
        assert result.claims_yoy_pct is None
