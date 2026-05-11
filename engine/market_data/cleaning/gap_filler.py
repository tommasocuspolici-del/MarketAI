"""Gap filling helpers used by :class:`DataCleaner`.

For OHLCV daily series:
  · weekends and holidays are NOT considered gaps
  · gaps inside the trading week are filled by forward-fill (default)
  · gaps spanning more than ``max_gap_days`` are left as-is and reported

For macro series, frequency is inferred (or supplied) and the same logic
applies adapted to the cadence.
"""
from __future__ import annotations

import pandas as pd

from shared.logger import get_logger

__version__ = "6.0.0"

__all__ = ["count_gaps_business_days", "forward_fill_short_gaps"]

log = get_logger(__name__)


def count_gaps_business_days(
    timestamps: pd.Series,
) -> int:
    """Count missing business days between first and last timestamp.

    Args:
        timestamps: A timezone-aware datetime Series (UTC).

    Returns:
        Number of business days expected but absent from the series.
        Returns 0 if fewer than 2 timestamps.
    """
    if len(timestamps) < 2:
        return 0

    # Normalizziamo a date-only per il conteggio business-day; preserviamo TZ
    ts_sorted = timestamps.sort_values()
    start = ts_sorted.iloc[0].normalize()
    end = ts_sorted.iloc[-1].normalize()

    # Business days attesi nell'intervallo (esclude sabato/domenica)
    expected_idx = pd.bdate_range(start=start, end=end, tz=timestamps.dt.tz)
    actual_dates = ts_sorted.dt.normalize().drop_duplicates()
    # Conteggio via set: Series.intersection non esiste, ma la conversione è O(n)
    actual_set = set(actual_dates)
    expected_set = set(expected_idx)
    missing = len(expected_set - actual_set)
    return max(0, int(missing))


def forward_fill_short_gaps(
    df: pd.DataFrame,
    ts_col: str = "ts",
    max_gap_days: int = 7,
    columns: list[str] | None = None,
) -> tuple[pd.DataFrame, int]:
    """Forward-fill NaN values within short gaps.

    Args:
        df: DataFrame sorted by ``ts_col``.
        ts_col: Timestamp column name.
        max_gap_days: Do not fill a NaN if its predecessor is older than this.
        columns: Subset of columns to fill. Default: all numeric columns.

    Returns:
        ``(filled_df, n_filled)`` where n_filled is how many NaNs were imputed.
    """
    if df.empty:
        return df, 0

    out = df.sort_values(ts_col).reset_index(drop=True).copy()
    target_cols = columns if columns is not None else out.select_dtypes(include="number").columns.tolist()

    n_filled_total = 0
    for col in target_cols:
        if col not in out.columns:
            continue
        original_nans = out[col].isna()
        if not original_nans.any():
            continue

        # Forward-fill: ogni NaN prende il valore precedente
        filled = out[col].ffill()

        # Se max_gap_days impostato, annulla i fill su gap troppo lunghi
        if max_gap_days > 0:
            ts = out[ts_col]
            # Ultimo timestamp con valore non-NaN visto, propagato in avanti
            last_valid_ts = ts.where(out[col].notna()).ffill()
            gap_days = (ts - last_valid_ts).dt.days
            too_long = gap_days > max_gap_days
            # Per i gap troppo lunghi, ripristina NaN (annulla il fill)
            filled = filled.where(~too_long, other=pd.NA)

        # Conteggio: quanti NaN originali sono stati effettivamente riempiti
        actually_filled = original_nans & filled.notna()
        n_filled_total += int(actually_filled.sum())
        out[col] = filled

    return out, n_filled_total
