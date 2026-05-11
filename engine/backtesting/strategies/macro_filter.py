"""Macro-filter strategy.

Wraps a base strategy and gates its long signals through a macro-context
guard. Concretely: only let the wrapped strategy's positions through when
a configurable macro time-series (e.g. VIX) is below a threshold —
"defensive mode off". This is the canonical pattern for incorporating
macro context into an equity strategy.

The macro series is supplied as a separate aligned DataFrame; the wrapper
reindexes it onto the OHLCV timestamps with forward-fill (macro updates
slower than prices).
"""
from __future__ import annotations

import pandas as pd

from engine.backtesting.strategy import Strategy, StrategySignal
from shared.exceptions import BacktestError

__version__ = "6.0.0"

__all__ = ["MacroFilter"]


class MacroFilter(Strategy):
    """Apply a macro indicator gate on top of a wrapped strategy.

    Args:
        base_strategy: The underlying strategy whose signals get filtered.
        macro_series: DataFrame with columns ``ts`` and ``value`` (the
            macro indicator, e.g. VIX close). Will be aligned to the OHLCV
            index via forward-fill.
        threshold: Allow signals only when macro_value <= threshold (mode
            'low_is_good'). For 'high_is_good' invert the comparison.
        mode: ``"low_is_good"`` (e.g. low VIX = risk-on) or ``"high_is_good"``.
    """

    def __init__(
        self,
        base_strategy: Strategy,
        macro_series: pd.DataFrame,
        threshold: float,
        mode: str = "low_is_good",
    ) -> None:
        if mode not in ("low_is_good", "high_is_good"):
            raise BacktestError(
                f"mode must be 'low_is_good' or 'high_is_good', got '{mode}'"
            )
        if "ts" not in macro_series.columns or "value" not in macro_series.columns:
            raise BacktestError(
                "macro_series must have 'ts' and 'value' columns"
            )
        self._base = base_strategy
        self._macro = macro_series
        self._threshold = threshold
        self._mode = mode

    @property
    def name(self) -> str:
        return f"MacroFilter[{self._base.name}|thr={self._threshold}|{self._mode}]"

    def generate_signals(self, ohlcv: pd.DataFrame) -> StrategySignal:
        # 1. Genera segnali della strategia di base
        base_sig = self._base.generate_signals(ohlcv)

        # 2. Allinea la serie macro all'indice ts dell'OHLCV con ffill
        if "ts" not in ohlcv.columns:
            raise BacktestError("OHLCV DataFrame missing 'ts' column for MacroFilter")

        macro_aligned = self._align_macro_to_ohlcv(ohlcv["ts"])

        # 3. Costruisci la maschera vettorizzata (Regola 23: zero loop)
        if self._mode == "low_is_good":
            allow_mask = (macro_aligned <= self._threshold).astype("float64")
        else:
            allow_mask = (macro_aligned >= self._threshold).astype("float64")

        # NaN macro (prima del primo valore) → flat (allow=0)
        allow_mask = allow_mask.fillna(0.0).reset_index(drop=True)

        # 4. Maschera applicata: tieni solo i segnali long quando macro è amichevole
        # Per gli short, lasciamo passare sempre (un mercato avverso autorizza
        # le posizioni difensive). Questa è una convention; può essere parametrizzata.
        base_positions = base_sig.positions.reset_index(drop=True)
        long_part = base_positions.clip(lower=0.0) * allow_mask
        short_part = base_positions.clip(upper=0.0)
        filtered = long_part + short_part

        return StrategySignal(
            positions=filtered.set_axis(base_sig.positions.index),
            name=self.name,
            params={
                "base_strategy": self._base.name,
                "threshold": self._threshold,
                "mode": self._mode,
            },
        )

    def _align_macro_to_ohlcv(self, ohlcv_ts: pd.Series) -> pd.Series:
        """Forward-fill macro values onto the OHLCV timestamps."""
        # Costruzione DataFrame indicizzato sui ts macro per merge_asof
        macro = self._macro[["ts", "value"]].sort_values("ts").reset_index(drop=True)
        ohlcv_df = pd.DataFrame({"ts": ohlcv_ts.reset_index(drop=True)})
        # merge_asof: per ogni ts OHLCV trova l'ultimo ts macro <= (ffill semantics)
        merged = pd.merge_asof(
            ohlcv_df, macro, on="ts", direction="backward",
        )
        return merged["value"].astype("float64")
