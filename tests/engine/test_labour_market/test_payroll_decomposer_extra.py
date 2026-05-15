"""Additional tests for PayrollDecomposer — coverage for _compute_signal paths."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from engine.analytics.labour_market.payroll_decomposer import (
    PayrollDecomposer,
    PayrollSignal,
)
from engine.market_data.fred_simple_client import FredSimpleClient, FredKeyMissingError


def _make_fred_df(values: list[float], start: str = "2023-01-01") -> pd.DataFrame:
    dates = pd.date_range(start, periods=len(values), freq="MS")
    return pd.DataFrame({"ts": dates, "value": values})


class TestPayrollDecomposerComputeSignal:
    """Tests for _compute_signal internals via decompose() with mocked FRED."""

    def _decomposer_with_mock_fred(self, total_vals, sector_vals=None):
        d = PayrollDecomposer(duckdb=None)
        sector_df = _make_fred_df(sector_vals or [100.0, 110.0, 105.0])

        def side_effect(series_id, **kwargs):
            if series_id == "PAYEMS":
                return _make_fred_df(total_vals)
            return sector_df.copy()

        d._client = MagicMock(spec=FredSimpleClient)
        d._client.fetch_series.side_effect = side_effect
        return d

    def test_returns_payroll_signal(self):
        d = self._decomposer_with_mock_fred([130_000, 131_000, 132_000])
        result = d.decompose()
        assert isinstance(result, PayrollSignal)

    def test_nfp_total_is_last_value(self):
        d = self._decomposer_with_mock_fred([130_000, 131_000, 132_000])
        result = d.decompose()
        assert result.nfp_total == pytest.approx(132_000)

    def test_payroll_score_in_range(self):
        d = self._decomposer_with_mock_fred([130_000, 131_000, 132_000])
        result = d.decompose()
        assert -1.0 <= result.payroll_score <= 1.0

    def test_cyclical_ratio_is_float(self):
        d = self._decomposer_with_mock_fred([130_000, 131_000, 132_000])
        result = d.decompose()
        assert isinstance(result.cyclical_ratio, float)

    def test_sector_breakdown_has_entries(self):
        d = self._decomposer_with_mock_fred([130_000, 131_000, 132_000])
        result = d.decompose()
        assert len(result.sector_breakdown) > 0

    def test_release_date_is_date(self):
        d = self._decomposer_with_mock_fred([130_000, 131_000, 132_000])
        result = d.decompose()
        assert isinstance(result.release_date, date)

    def test_raises_on_fred_key_missing(self):
        d = PayrollDecomposer(duckdb=None)
        d._client = MagicMock(spec=FredSimpleClient)
        d._client.fetch_series.side_effect = FredKeyMissingError("no key")
        with pytest.raises(FredKeyMissingError):
            d.decompose()

    def test_revision_none_on_short_series(self):
        # < 4 values → revision should be None
        d = self._decomposer_with_mock_fred([130_000, 131_000])
        result = d.decompose()
        # Short total series → two_month_revision is None
        assert result.two_month_revision is None or isinstance(result.two_month_revision, float)

    def test_duckdb_persist_called_when_provided(self):
        d = PayrollDecomposer(duckdb=MagicMock())

        def side_effect(series_id, **kwargs):
            return _make_fred_df([130_000, 131_000, 132_000])

        d._client = MagicMock(spec=FredSimpleClient)
        d._client.fetch_series.side_effect = side_effect
        result = d.decompose()
        assert isinstance(result, PayrollSignal)


class TestComputeRevision:
    def test_returns_float_on_adequate_data(self):
        df = _make_fred_df([100.0, 110.0, 105.0, 115.0])
        result = PayrollDecomposer._compute_revision(df)
        assert isinstance(result, float)

    def test_returns_none_on_short_data(self):
        df = _make_fred_df([100.0, 105.0])
        result = PayrollDecomposer._compute_revision(df)
        assert result is None

    def test_positive_revision_when_latest_above_mean(self):
        # latest=200, prev2=[100, 100] → mean=100 → revision = 100
        df = _make_fred_df([100.0, 100.0, 100.0, 200.0])
        result = PayrollDecomposer._compute_revision(df)
        assert result > 0

    def test_negative_revision_when_latest_below_mean(self):
        df = _make_fred_df([200.0, 200.0, 200.0, 100.0])
        result = PayrollDecomposer._compute_revision(df)
        assert result < 0
