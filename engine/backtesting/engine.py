"""Vectorized backtest engine (Rule 23).

This is a VectorBT-API-compatible engine implemented natively in numpy
when the `vectorbt` package is unavailable. It enforces the same
invariants the roadmap requires:

  · NO Python loops over time series
  · ``fees >= 0.001`` and ``slippage >= 0.001`` are NON-NEGOTIABLE
  · Signals are SHIFTED BY 1 BAR before execution (anti look-ahead)
  · DataQualityReport must satisfy quality_score >= 0.7 before backtest
    runs (Rule 26 critical-data threshold for backtest)

Outputs:
  · BacktestResult dataclass with equity curve + PerformanceReport
  · WalkForwardResult for out-of-sample validation across N splits

Usage:
    engine = BacktestEngine(initial_cash=10_000.0)
    result = engine.run(ohlcv_df, strategy)
    wf_result = engine.walk_forward(ohlcv_df, strategy, n_splits=5)
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from engine.backtesting.performance import PerformanceReport, compute_performance_report
from shared.exceptions import BacktestError, DataQualityError
from shared.logger import get_logger
from shared.metrics import metrics

if TYPE_CHECKING:
    from engine.backtesting.strategy import Strategy
    from shared.db.quality import DataQualityReport

__version__ = "6.0.0"

__all__ = [
    "MIN_FEES",
    "MIN_QUALITY_FOR_BACKTEST",
    "MIN_SLIPPAGE",
    "BacktestEngine",
    "BacktestResult",
    "WalkForwardResult",
]

log = get_logger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# Non-negotiable invariants (Rule 23 + Rule 26)
# ═══════════════════════════════════════════════════════════════════════════
MIN_FEES: float = 0.001          # 0.10% commissioni minime per lato
MIN_SLIPPAGE: float = 0.001       # 0.10% slippage minimo per lato
MIN_QUALITY_FOR_BACKTEST: float = 0.7  # quality_score >= 0.7 (Rule 26)


# ═══════════════════════════════════════════════════════════════════════════
# Result dataclasses
# ═══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Outcome of a single in-sample backtest run."""

    strategy_name: str
    ticker: str
    equity_curve: pd.Series          # NAV over time
    positions: pd.Series              # Realized positions (post-shift)
    returns: pd.Series                # Period log-returns
    performance: PerformanceReport
    fees_total: float                 # Sum of fees paid
    n_trades: int                     # Number of position changes
    initial_cash: float


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    """Outcome of a walk-forward validation run."""

    strategy_name: str
    ticker: str
    n_splits: int
    split_results: list[BacktestResult]
    aggregate_performance: PerformanceReport  # On stitched OOS equity


# ═══════════════════════════════════════════════════════════════════════════
# Engine
# ═══════════════════════════════════════════════════════════════════════════
class BacktestEngine:
    """Vectorized backtest engine."""

    def __init__(
        self,
        initial_cash: float = 10_000.0,
        fees: float = MIN_FEES,
        slippage: float = MIN_SLIPPAGE,
    ) -> None:
        # Regola 23: fees e slippage minimi NON negoziabili
        if fees < MIN_FEES:
            raise BacktestError(
                f"fees ({fees}) below minimum {MIN_FEES} (Rule 23 violation)"
            )
        if slippage < MIN_SLIPPAGE:
            raise BacktestError(
                f"slippage ({slippage}) below minimum {MIN_SLIPPAGE} (Rule 23 violation)"
            )
        if initial_cash <= 0:
            raise BacktestError(f"initial_cash must be > 0, got {initial_cash}")

        self._initial_cash = initial_cash
        self._fees = fees
        self._slippage = slippage

    # ─── Single-shot backtest ───────────────────────────────────────────
    def run(
        self,
        ohlcv: pd.DataFrame,
        strategy: Strategy,
        ticker: str = "UNKNOWN",
        quality_report: DataQualityReport | None = None,
    ) -> BacktestResult:
        """Execute a backtest.

        Args:
            ohlcv: OHLCV DataFrame already cleaned + validated.
            strategy: Strategy instance whose ``generate_signals`` produces
                positions in [-1, 1].
            ticker: Identifier (used in result + persistence).
            quality_report: If provided, must have quality_score >= 0.7
                (Rule 26). If None, the check is skipped — caller's
                responsibility.
        """
        # Regola 26: rifiuta dati di bassa qualità per i backtest
        if quality_report is not None and quality_report.quality_score < MIN_QUALITY_FOR_BACKTEST:
            raise DataQualityError(
                series_id=quality_report.series_id,
                score=quality_report.quality_score,
                minimum=MIN_QUALITY_FOR_BACKTEST,
            )

        if len(ohlcv) < 2:
            raise BacktestError(f"need at least 2 bars to backtest, got {len(ohlcv)}")
        if "close" not in ohlcv.columns:
            raise BacktestError("OHLCV missing 'close' column")

        with metrics.timer("backtest_run_ms", strategy=strategy.name, ticker=ticker):
            # 1. Strategia produce segnali grezzi
            signal = strategy.generate_signals(ohlcv)
            raw_positions = signal.positions.astype("float64")

            # 2. Anti-lookahead (Regola 23): segnale al tempo t agisce a t+1
            executed_positions = raw_positions.shift(1).fillna(0.0)

            # 3. Esecuzione vettorizzata: ritorni close-to-close
            close = ohlcv["close"].astype("float64")
            close_returns = close.pct_change().fillna(0.0).to_numpy()

            # 4. Fees + slippage applicati al cambio di posizione
            #    cost = (|delta_pos|) * (fees + slippage)
            pos_array = executed_positions.to_numpy()
            position_changes = np.abs(np.diff(pos_array, prepend=0.0))
            costs_per_bar = position_changes * (self._fees + self._slippage)

            # 5. Strategy returns: pos[t] * close_return[t] - costs[t]
            strategy_returns = pos_array * close_returns - costs_per_bar

            # 6. Equity curve: cumprod su (1 + r), partendo da initial_cash
            equity = self._initial_cash * np.cumprod(1.0 + strategy_returns)

            # 7. Conteggi per il report
            fees_total = float(costs_per_bar.sum() * self._initial_cash)
            n_trades = int((position_changes > 1e-9).sum())

        # 8. Performance metrics
        equity_series = pd.Series(equity, index=ohlcv.index, dtype="float64")
        perf = compute_performance_report(equity_series)

        log.info(
            "backtest.run_done",
            strategy=strategy.name,
            ticker=ticker,
            sharpe=round(perf.sharpe_ratio, 3),
            max_dd=round(perf.max_drawdown, 3),
            n_trades=n_trades,
        )

        return BacktestResult(
            strategy_name=strategy.name,
            ticker=ticker,
            equity_curve=equity_series,
            positions=executed_positions,
            returns=pd.Series(strategy_returns, index=ohlcv.index, dtype="float64"),
            performance=perf,
            fees_total=fees_total,
            n_trades=n_trades,
            initial_cash=self._initial_cash,
        )

    # ─── Walk-forward validation ────────────────────────────────────────
    def walk_forward(
        self,
        ohlcv: pd.DataFrame,
        strategy: Strategy,
        ticker: str = "UNKNOWN",
        n_splits: int = 5,
        train_pct: float = 0.6,
    ) -> WalkForwardResult:
        """Walk-forward validation: train on past, test on next slice.

        Method: divide data into ``n_splits`` overlapping windows. For each
        window, the model "trains" on the first ``train_pct`` of bars (no
        actual training in our current strategies — they're parametric),
        then tests on the remaining bars. Out-of-sample equity curves are
        stitched together for aggregate stats.

        Args:
            ohlcv: DataFrame already cleaned.
            strategy: Strategy to evaluate.
            ticker: Identifier.
            n_splits: Number of walk-forward windows.
            train_pct: Fraction of each window used as in-sample (rest = OOS).
        """
        if n_splits < 2:
            raise BacktestError(f"n_splits must be >= 2, got {n_splits}")
        if not 0.1 <= train_pct <= 0.9:
            raise BacktestError(f"train_pct must be in [0.1, 0.9], got {train_pct}")
        if len(ohlcv) < 100:
            raise BacktestError(
                f"need at least 100 bars for walk-forward, got {len(ohlcv)}"
            )

        with metrics.timer(
            "backtest_walkforward_ms", strategy=strategy.name, ticker=ticker
        ):
            split_size = len(ohlcv) // n_splits
            split_results: list[BacktestResult] = []
            oos_equity_pieces: list[pd.Series] = []

            for i in range(n_splits):
                start_idx = i * split_size
                end_idx = (i + 1) * split_size if i < n_splits - 1 else len(ohlcv)
                window = ohlcv.iloc[start_idx:end_idx].copy()
                if len(window) < 20:
                    continue
                # Solo la parte test (out-of-sample) entra nel risultato
                test_start = int(len(window) * train_pct)
                test_window = window.iloc[test_start:].copy()
                if len(test_window) < 5:
                    continue
                sub_result = self.run(test_window, strategy, ticker=f"{ticker}_split{i}")
                split_results.append(sub_result)
                oos_equity_pieces.append(sub_result.equity_curve)

        if not oos_equity_pieces:
            raise BacktestError("walk-forward produced no usable splits")

        # Aggregate OOS equity curve: rinormalizza e concatena
        aggregate = self._stitch_equity_curves(oos_equity_pieces)
        aggregate_perf = compute_performance_report(aggregate)

        log.info(
            "backtest.walk_forward_done",
            strategy=strategy.name,
            ticker=ticker,
            splits=len(split_results),
            agg_sharpe=round(aggregate_perf.sharpe_ratio, 3),
        )
        return WalkForwardResult(
            strategy_name=strategy.name,
            ticker=ticker,
            n_splits=len(split_results),
            split_results=split_results,
            aggregate_performance=aggregate_perf,
        )

    @staticmethod
    def _stitch_equity_curves(pieces: list[pd.Series]) -> pd.Series:
        """Concatenate equity curves rebasing each segment to the previous end."""
        if not pieces:
            return pd.Series([], dtype="float64")

        stitched = [pieces[0]]
        for prev, curr in itertools.pairwise(pieces):
            scale = float(prev.iloc[-1] / curr.iloc[0]) if curr.iloc[0] != 0 else 1.0
            stitched.append(curr * scale)
        return pd.concat(stitched)
