"""RegimeAwareBacktestEngine — regime-conditioned strategy backtesting.

Splits the backtest into regime sub-periods (bull / bear / stress / transition)
and evaluates strategy performance independently in each regime. Produces
per-regime Sharpe, win-rate, and drawdown metrics.

Key insight: a strategy that wins in bull but fails in bear is NOT a good
strategy — it's a bull-market artefact. This engine makes regime performance
transparent and comparable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from shared.logger import get_logger

__version__ = "10.0.0"

__all__ = [
    "RegimeBacktestResult",
    "RegimeAwareBacktestEngine",
]

log = get_logger(__name__)

_REGIMES = ("bull", "bear", "stress", "transition")
_RISK_FREE = 0.04


@dataclass
class RegimeBacktestResult:
    """Per-regime backtest statistics."""
    regime:          str
    n_days:          int
    sharpe:          float
    total_return:    float     # Fraction, e.g. 0.15 = 15%
    max_drawdown:    float     # Fraction, negative number
    win_rate:        float     # Fraction of profitable trades
    n_trades:        int


@dataclass
class BacktestSummary:
    """Complete backtest output across all regimes."""
    strategy_id:     str
    ticker:          str
    per_regime:      dict[str, RegimeBacktestResult]
    overall_sharpe:  float
    overall_return:  float
    is_regime_robust: bool     # True if Sharpe > 0 in at least 3 of 4 regimes


class RegimeAwareBacktestEngine:
    """Backtest a strategy across regime sub-periods.

    Usage::

        engine = RegimeAwareBacktestEngine()
        summary = engine.run(
            ohlcv         = df,
            regime_labels = regime_series,   # pd.Series[str] indexed like ohlcv
            strategy_fn   = my_strategy,     # fn(df) → (entries, exits)
            strategy_id   = "sma_crossover",
            ticker        = "SPY",
        )
    """

    def run(
        self,
        ohlcv:         pd.DataFrame,
        regime_labels: pd.Series,
        strategy_fn:   Callable[[pd.DataFrame], tuple[pd.Series, pd.Series]],
        strategy_id:   str = "unnamed",
        ticker:        str = "SPY",
    ) -> BacktestSummary:
        """Run regime-aware backtest.

        Args:
            ohlcv:         OHLCV DataFrame with DatetimeIndex, 'close' column required.
            regime_labels: pd.Series mapping date → regime string.
            strategy_fn:   fn(full_ohlcv) → (entries, exits) for the whole period.
            strategy_id:   Name for logging and registry.
            ticker:        Instrument name.
        """
        # Generate signals on full period
        try:
            entries, exits = strategy_fn(ohlcv)
        except Exception as exc:
            log.error("regime_engine.strategy_failed", error=str(exc))
            return self._empty_summary(strategy_id, ticker)

        per_regime: dict[str, RegimeBacktestResult] = {}

        for regime in _REGIMES:
            mask = regime_labels.reindex(ohlcv.index).fillna("transition") == regime
            regime_idx = ohlcv.index[mask]

            if len(regime_idx) < 20:
                log.debug("regime_engine.regime_skipped", regime=regime, n=len(regime_idx))
                continue

            r_ohlcv   = ohlcv.loc[regime_idx]
            r_entries = entries.reindex(regime_idx).fillna(False)
            r_exits   = exits.reindex(regime_idx).fillna(False)

            result = self._evaluate_regime(regime, r_ohlcv, r_entries, r_exits)
            per_regime[regime] = result

        overall_sharpe, overall_return = self._overall_stats(ohlcv, entries, exits)
        positive_regimes = sum(1 for r in per_regime.values() if r.sharpe > 0)
        is_robust = positive_regimes >= 3

        log.info(
            "regime_engine.complete",
            strategy=strategy_id,
            ticker=ticker,
            overall_sharpe=round(overall_sharpe, 3),
            robust=is_robust,
            regimes=list(per_regime.keys()),
        )
        return BacktestSummary(
            strategy_id      = strategy_id,
            ticker           = ticker,
            per_regime       = per_regime,
            overall_sharpe   = round(overall_sharpe, 4),
            overall_return   = round(overall_return, 4),
            is_regime_robust = is_robust,
        )

    # ── Internal ───────────────────────────────────────────────────────────

    def _evaluate_regime(
        self,
        regime:   str,
        ohlcv:    pd.DataFrame,
        entries:  pd.Series,
        exits:    pd.Series,
    ) -> RegimeBacktestResult:
        try:
            import vectorbt as vbt  # type: ignore[import-untyped]  # noqa: PLC0415
            pf    = vbt.Portfolio.from_signals(
                ohlcv["close"], entries.shift(1).fillna(False),
                exits.shift(1).fillna(False), fees=0.001, slippage=0.001, freq="1D",
            )
            stats = pf.stats()
            raw_sharpe = float(stats.get("Sharpe Ratio", 0.0) or 0.0)
            sharpe    = float(np.clip(raw_sharpe, -50.0, 50.0)) if np.isfinite(raw_sharpe) else 0.0
            tot_ret   = float(stats.get("Total Return [%]", 0.0) or 0.0) / 100.0
            mdd_raw   = float(stats.get("Max Drawdown [%]", 0.0) or 0.0)
            mdd       = float(np.clip(-abs(mdd_raw) / 100.0, -1.0, 0.0))
            n_trades  = int(stats.get("Total Trades", 0)         or 0)
            win_rate  = float(stats.get("Win Rate [%]", 0.0)     or 0.0) / 100.0
        except Exception:
            sharpe, tot_ret, mdd, n_trades, win_rate = self._numpy_regime_stats(
                ohlcv, entries, exits
            )

        return RegimeBacktestResult(
            regime       = regime,
            n_days       = len(ohlcv),
            sharpe       = round(sharpe, 4),
            total_return = round(tot_ret, 4),
            max_drawdown = round(mdd, 4),
            win_rate     = round(win_rate, 4),
            n_trades     = n_trades,
        )

    @staticmethod
    def _numpy_regime_stats(
        ohlcv:   pd.DataFrame,
        entries: pd.Series,
        exits:   pd.Series,
    ) -> tuple[float, float, float, int, float]:
        close = ohlcv["close"].values.astype(np.float64)
        rets  = np.diff(close) / close[:-1]
        e_arr = entries.values[:-1].astype(bool)
        x_arr = exits.values[:-1].astype(bool)

        position = np.zeros(len(rets))
        in_trade = False
        trades: list[float] = []
        trade_ret = 0.0
        for i in range(len(rets)):
            if e_arr[i] and not in_trade:
                in_trade  = True
                trade_ret = 0.0
            if in_trade:
                trade_ret += rets[i]
            if x_arr[i] and in_trade:
                trades.append(trade_ret)
                in_trade = False
            position[i] = 1.0 if in_trade else 0.0

        strat_rets = rets * position
        if strat_rets.std() < 1e-9:
            sharpe = 0.0
        else:
            daily_rf = _RISK_FREE / 252
            excess   = strat_rets - daily_rf
            sharpe   = float(np.sqrt(252) * excess.mean() / excess.std())

        tot_ret  = float(np.prod(1 + strat_rets) - 1)
        cum      = np.cumprod(1 + strat_rets)
        peak     = np.maximum.accumulate(cum)
        mdd      = float(np.min((cum - peak) / np.where(peak > 0, peak, 1)))
        n_trades = len(trades)
        win_rate = float(np.mean([t > 0 for t in trades])) if trades else 0.0

        return sharpe, tot_ret, mdd, n_trades, win_rate

    @staticmethod
    def _overall_stats(
        ohlcv:   pd.DataFrame,
        entries: pd.Series,
        exits:   pd.Series,
    ) -> tuple[float, float]:
        try:
            import vectorbt as vbt  # noqa: PLC0415
            pf    = vbt.Portfolio.from_signals(
                ohlcv["close"],
                entries.shift(1).fillna(False),
                exits.shift(1).fillna(False),
                fees=0.001, slippage=0.001, freq="1D",
            )
            stats = pf.stats()
            raw_s = float(stats.get("Sharpe Ratio", 0.0) or 0.0)
            sharpe = float(np.clip(raw_s, -50.0, 50.0)) if np.isfinite(raw_s) else 0.0
            return sharpe, float(stats.get("Total Return [%]", 0.0) or 0.0) / 100.0
        except Exception:
            close = ohlcv["close"].values.astype(np.float64)
            rets  = np.diff(close) / close[:-1]
            e     = entries.values[:-1].astype(bool)
            pos   = np.zeros(len(rets))
            in_t  = False
            for i in range(len(rets)):
                if e[i]: in_t = True
                pos[i] = 1.0 if in_t else 0.0
            sr = rets * pos
            if sr.std() < 1e-9:
                return 0.0, float(np.prod(1 + sr) - 1)
            daily_rf = _RISK_FREE / 252
            excess   = sr - daily_rf
            sharpe   = float(np.sqrt(252) * excess.mean() / excess.std())
            return sharpe, float(np.prod(1 + sr) - 1)

    @staticmethod
    def _empty_summary(strategy_id: str, ticker: str) -> BacktestSummary:
        return BacktestSummary(
            strategy_id      = strategy_id,
            ticker           = ticker,
            per_regime       = {},
            overall_sharpe   = 0.0,
            overall_return   = 0.0,
            is_regime_robust = False,
        )
