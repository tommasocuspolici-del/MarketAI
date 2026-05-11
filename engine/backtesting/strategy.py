"""Strategy contract for the backtesting engine.

A strategy is a pure mapping from (price_history, parameters) to a
position-target series in [-1, 1]:
  ·  1.0 = full long
  · -1.0 = full short
  ·  0.0 = flat / cash

The engine handles execution: applying the position with shift(1) for
anti-lookahead (Rule 23), commissions, slippage, and equity computation.
Strategies NEVER touch fees / slippage / shift logic themselves — they
only emit raw position signals.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import pandas as pd

from shared.exceptions import BacktestError
from shared.logger import get_logger

__version__ = "6.0.0"

__all__ = ["Strategy", "StrategySignal"]

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class StrategySignal:
    """Result of a strategy applied to an OHLCV DataFrame.

    Attributes:
        positions: Float series in [-1.0, 1.0]; same index as input.
        name: Human-readable strategy name (used in reports).
        params: Dict of hyperparameters for reproducibility.
    """

    positions: pd.Series
    name: str
    params: dict[str, float | int | str]

    def __post_init__(self) -> None:
        # Verifica valori in range [-1, 1] (post-condition contrattuale)
        if len(self.positions) > 0:
            min_v = float(self.positions.min())
            max_v = float(self.positions.max())
            if min_v < -1.0 or max_v > 1.0:
                raise BacktestError(
                    f"Strategy '{self.name}' emitted positions out of [-1, 1]: "
                    f"min={min_v:.3f}, max={max_v:.3f}"
                )


class Strategy(ABC):
    """Abstract base for all backtesting strategies."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy identifier used in reports / persistence."""

    @abstractmethod
    def generate_signals(self, ohlcv: pd.DataFrame) -> StrategySignal:
        """Compute the position-target series.

        Args:
            ohlcv: DataFrame with at least ``ts`` and ``close`` columns,
                already cleaned and validated by ``DataCleaner``.

        Returns:
            ``StrategySignal`` with positions in [-1, 1].

        Notes:
            Implementations MUST NOT shift the signals themselves; the
            engine applies ``shift(1)`` to prevent look-ahead bias (Rule 23).
            However they CAN use ``.shift(k)`` internally to compute lagged
            features (e.g. previous close) — what matters is that the final
            position at time ``t`` only uses information from ``[0..t]``.
        """

    # ─── Helpers shared between strategies ─────────────────────────────
    @staticmethod
    def _ensure_close(ohlcv: pd.DataFrame) -> pd.Series:
        """Validate input and return the close price series."""
        if "close" not in ohlcv.columns:
            raise BacktestError("OHLCV DataFrame missing 'close' column")
        if len(ohlcv) == 0:
            raise BacktestError("OHLCV DataFrame is empty — no data to backtest")
        return ohlcv["close"].astype("float64")

    @staticmethod
    def _zero_signal(index: pd.Index, name: str, params: dict) -> StrategySignal:  # type: ignore[type-arg]
        """Build a flat (all-zero) signal — used as a safe default."""
        return StrategySignal(
            positions=pd.Series(np.zeros(len(index), dtype="float64"), index=index),
            name=name,
            params=params,
        )
