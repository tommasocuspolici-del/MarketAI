"""Tests for engine.market_data.cleaning.outlier_detector."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.market_data.cleaning.outlier_detector import (
    detect_outliers_iqr,
    detect_outliers_zscore,
)


class TestDetectOutliersZScore:
    def test_normal_distribution_no_outliers(self) -> None:
        rng = np.random.default_rng(seed=42)
        # Distribuzione normale standard: nessun outlier oltre 4sigma con n=200
        s = pd.Series(rng.standard_normal(200))
        mask = detect_outliers_zscore(s, threshold=4.0)
        assert mask.sum() == 0

    def test_synthetic_outliers_flagged(self) -> None:
        # Serie costante con un singolo outlier estremo
        values = [1.0] * 50 + [100.0] + [1.0] * 50
        s = pd.Series(values)
        mask = detect_outliers_zscore(s, threshold=2.0)
        # Almeno il punto con valore 100 deve essere flaggato
        assert mask.iloc[50] is np.True_ or mask.iloc[50]

    def test_constant_series_no_outliers(self) -> None:
        s = pd.Series([5.0] * 100)
        mask = detect_outliers_zscore(s)
        # std=0 → nessun outlier definibile
        assert mask.sum() == 0

    def test_empty_series(self) -> None:
        s = pd.Series([], dtype=float)
        mask = detect_outliers_zscore(s)
        assert len(mask) == 0
        assert mask.dtype == bool

    def test_rolling_window_more_lenient_on_trends(self) -> None:
        # Serie con trend lineare: rolling z-score non flagga il trend stesso
        s = pd.Series(np.arange(100, dtype=float))
        mask = detect_outliers_zscore(s, threshold=4.0, rolling_window=10)
        # Trend pulito: nessun (o quasi) outlier
        assert mask.sum() < 5

    def test_nan_inputs_become_false(self) -> None:
        s = pd.Series([1.0, 2.0, np.nan, 4.0, 5.0])
        mask = detect_outliers_zscore(s)
        # Nessun NaN nel mask di output (deterministico)
        assert mask.dtype == bool
        assert not mask.isna().any()


class TestDetectOutliersIqr:
    def test_normal_distribution_few_outliers(self) -> None:
        rng = np.random.default_rng(seed=7)
        s = pd.Series(rng.standard_normal(500))
        mask = detect_outliers_iqr(s, multiplier=3.0)
        # Soglia permissiva (3.0): pochissimi outlier su distribuzione normale
        assert mask.sum() <= 10

    def test_extreme_value_flagged(self) -> None:
        s = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 1000])
        mask = detect_outliers_iqr(s, multiplier=1.5)
        assert mask.iloc[-1]  # il 1000 deve essere outlier
        assert mask.sum() == 1

    def test_concentrated_distribution_no_outliers(self) -> None:
        s = pd.Series([5.0] * 50)
        mask = detect_outliers_iqr(s)
        # IQR=0 → nessun outlier definibile
        assert mask.sum() == 0

    def test_empty_series(self) -> None:
        s = pd.Series([], dtype=float)
        mask = detect_outliers_iqr(s)
        assert len(mask) == 0


@pytest.mark.parametrize("method_fn", [detect_outliers_zscore, detect_outliers_iqr])
class TestOutlierContract:
    """Properties that ALL outlier detectors must satisfy."""

    def test_returns_boolean_series(self, method_fn) -> None:
        s = pd.Series([1.0, 2.0, 3.0, 100.0])
        mask = method_fn(s)
        assert mask.dtype == bool

    def test_output_length_matches_input(self, method_fn) -> None:
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        mask = method_fn(s)
        assert len(mask) == len(s)
