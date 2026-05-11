"""Outlier detection helpers used by :class:`DataCleaner`.

Two strategies supported:
  · ``zscore``: mark points where |x - μ| / sigma exceeds a threshold
  · ``iqr``: mark points outside [Q1 - k·IQR, Q3 + k·IQR]

Both work on a single numeric column and return a boolean mask of the same
length where ``True`` means *outlier*. Detection only — caller decides
whether to drop, clip, or merely report.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from shared.logger import get_logger

__version__ = "6.0.0"

__all__ = ["detect_outliers_iqr", "detect_outliers_zscore"]

log = get_logger(__name__)


def detect_outliers_zscore(
    series: pd.Series,
    threshold: float = 4.0,
    rolling_window: int | None = None,
) -> pd.Series:
    """Return a boolean mask flagging Z-score outliers.

    Args:
        series: Numeric pandas Series.
        threshold: |Z-score| above which a point is an outlier.
        rolling_window: If set, use a rolling mean/std of this window
            (more robust on non-stationary series like prices). If None,
            use global mean/std.

    Returns:
        Boolean Series of same length and index as input. NaN inputs are
        marked False (cannot say if outlier or not).
    """
    if len(series) == 0:
        return pd.Series([], dtype=bool, index=series.index)

    if rolling_window and rolling_window > 1 and len(series) >= rolling_window:
        # Rolling Z-score: più stabile su serie non stazionarie (prezzi)
        roll_mean = series.rolling(window=rolling_window, min_periods=2).mean()
        roll_std = series.rolling(window=rolling_window, min_periods=2).std()
        # Sostituiamo gli std nulli con NaN per evitare divisione per zero
        roll_std = roll_std.replace(0.0, np.nan)
        z = (series - roll_mean).abs() / roll_std
    else:
        std = series.std()
        if std == 0 or pd.isna(std):
            # Costante o tutti NaN: nessun outlier definibile
            return pd.Series(False, index=series.index)
        mean = series.mean()
        z = (series - mean).abs() / std

    # NaN nel z-score → tratti come non-outlier (boolean must be deterministic)
    mask = z > threshold
    return mask.fillna(False).astype(bool)


def detect_outliers_iqr(
    series: pd.Series,
    multiplier: float = 3.0,
) -> pd.Series:
    """Return a boolean mask flagging Tukey-IQR outliers.

    Args:
        series: Numeric pandas Series.
        multiplier: Fence multiplier (1.5 = standard, 3.0 = permissive).

    Returns:
        Boolean Series of same length and index as input.
    """
    if len(series) == 0:
        return pd.Series([], dtype=bool, index=series.index)

    q1 = series.quantile(0.25)
    q3 = series.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0 or pd.isna(iqr):
        # Distribuzione concentrata: nessun outlier
        return pd.Series(False, index=series.index)

    lower = q1 - multiplier * iqr
    upper = q3 + multiplier * iqr
    mask = (series < lower) | (series > upper)
    return mask.fillna(False).astype(bool)
