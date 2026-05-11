"""Stale data detection helpers used by :class:`DataCleaner`.

A series is considered "stale" when:
  · The most recent timestamp is older than ``max_age_days``, OR
  · The same value repeats for more than ``max_consecutive_same_value`` rows
    (typically a sign of a feed that is broken but still echoing the last
    delivered value).
"""
from __future__ import annotations

import pandas as pd

from shared.logger import get_logger
from shared.types import now_utc

__version__ = "6.0.0"

__all__ = ["count_consecutive_repeats", "count_stale_days"]

log = get_logger(__name__)


def count_stale_days(
    timestamps: pd.Series,
    reference: pd.Timestamp | None = None,
) -> int:
    """How many days since the most recent observation.

    Args:
        timestamps: UTC-aware datetime Series.
        reference: "Now" reference (UTC). Defaults to ``shared.types.now_utc``.

    Returns:
        Calendar days between most-recent timestamp and the reference.
        Zero if the data is current or the series is empty.
    """
    if len(timestamps) == 0:
        return 0

    ref = reference if reference is not None else pd.Timestamp(now_utc())
    last = timestamps.max()
    if last >= ref:
        # Dati datati nel futuro (clock skew o errore feed) → 0
        return 0
    delta = ref - last
    return max(0, int(delta.days))


def count_consecutive_repeats(
    series: pd.Series,
    max_consecutive: int = 5,
) -> int:
    """Count rows belonging to a "stuck-value" run longer than the threshold.

    Implementation: detect runs of identical consecutive values; if a run
    has length L > max_consecutive, count L - 1 stuck rows (excluding the
    first which is the legitimate value).

    Args:
        series: Numeric series to inspect.
        max_consecutive: Tolerated run length (anything above this is stale).

    Returns:
        Number of rows that are part of an over-long stuck-value run.
    """
    if len(series) <= max_consecutive:
        return 0

    # Identifica i run con shift+cumsum (idiomatico pandas)
    not_equal_to_prev = series != series.shift()
    run_id = not_equal_to_prev.cumsum()
    run_lengths = series.groupby(run_id).transform("size")

    # Considera solo run che superano la soglia
    too_long_mask = run_lengths > max_consecutive
    if not too_long_mask.any():
        return 0

    # Per ogni run stuck, il primo elemento è valido — gli altri sono stale
    # Quindi: conteggio = somma(L - 1) per ogni run troppo lungo, evitando
    # di contare due volte i run più lunghi. Si ottiene escludendo il primo
    # elemento di ogni run.
    is_first_of_run = not_equal_to_prev
    stale_rows = too_long_mask & ~is_first_of_run
    return int(stale_rows.sum())
