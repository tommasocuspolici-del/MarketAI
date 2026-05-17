"""Pivot detection utilities for pattern recognition.

Estratte da pattern_recognition.py per rispettare Regola 2 (≤ 400 righe).
Importate da PatternDetector e riusabili da altri moduli tecnici.

Regola 8: numpy vettorizzato, zero loop Python su serie temporali.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np
import numpy.typing as npt
from numpy.lib.stride_tricks import sliding_window_view

__version__ = "9.0.0"
__all__ = ["find_pivots", "normalised_slope", "ts_to_datetime"]


def find_pivots(
    close: npt.NDArray[Any],
    order: int = 5,
) -> tuple[npt.NDArray[Any], npt.NDArray[Any]]:
    """Trova pivot locali massimi e minimi sulla serie close.

    Usa sliding_window_view di numpy — zero loop Python (Regola 8).

    Args:
        close: Serie prezzi 1-D float64.
        order: Numero di barre a sx/dx del centro. Più alto = meno pivot.

    Returns:
        (high_indices, low_indices) — ndarray di indici nella serie originale.

    ANTI-REGRESSIONE: sliding_window_view richiede len(close) >= 2*order+1.
    Con meno dati restituisce array vuoti invece di ValueError.
    """
    min_len = 2 * order + 1
    if len(close) < min_len:
        return np.array([], dtype=np.intp), np.array([], dtype=np.intp)

    windows  = sliding_window_view(close, min_len)
    centers  = windows[:, order]
    is_high  = centers >= windows.max(axis=1)
    is_low   = centers <= windows.min(axis=1)

    return (
        (np.where(is_high)[0] + order).astype(np.intp),
        (np.where(is_low)[0]  + order).astype(np.intp),
    )


def normalised_slope(idx: npt.NDArray[Any], vals: npt.NDArray[Any]) -> float:
    """Slope della regressione lineare normalizzata per il prezzo medio."""
    if len(idx) < 2:
        return 0.0
    coeffs = np.polyfit(idx.astype(np.float64), vals.astype(np.float64), 1)
    mean_y = float(np.mean(vals)) or 1e-9
    return float(coeffs[0] / mean_y)


def ts_to_datetime(ts_val: Any) -> datetime:
    """Converte numpy Timestamp/datetime64 in datetime Python UTC-aware (Regola 19)."""
    try:
        import pandas as pd
        result: datetime = pd.Timestamp(ts_val).to_pydatetime()
        return result
    except Exception:  # noqa: BLE001
        return datetime.now(UTC)
