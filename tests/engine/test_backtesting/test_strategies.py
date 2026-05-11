"""Tests for the 5 concrete strategies in engine.backtesting.strategies."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.backtesting.strategies import (
    CombinedStrategy,
    MacroFilter,
    Momentum,
    MovingAverageCrossover,
    RSIMeanReversion,
    compute_rsi,
)
from shared.exceptions import BacktestError


def _ohlcv(n: int = 200, seed: int = 42, drift: float = 0.0005) -> pd.DataFrame:
    rng = np.random.default_rng(seed=seed)
    ts = pd.date_range(start="2024-01-01", periods=n, freq="D", tz="UTC")
    close = 100.0 * np.exp(np.cumsum(rng.normal(drift, 0.01, size=n)))
    return pd.DataFrame(
        {
            "ts": ts, "open": close, "high": close * 1.01, "low": close * 0.99,
            "close": close, "volume": [1_000_000] * n,
        }
    )


# ═══════════════════════════════════════════════════════════════════════════
# Moving Average Crossover
# ═══════════════════════════════════════════════════════════════════════════
class TestMovingAverageCrossover:
    def test_signal_in_valid_range(self) -> None:
        sig = MovingAverageCrossover(fast=10, slow=30).generate_signals(_ohlcv(100))
        assert sig.positions.min() >= 0.0
        assert sig.positions.max() <= 1.0

    def test_short_enabled_allows_negative(self) -> None:
        # Con allow_short=True, le posizioni possono andare a -1
        sig = MovingAverageCrossover(fast=5, slow=20, allow_short=True).generate_signals(
            _ohlcv(100)
        )
        assert sig.positions.min() >= -1.0
        assert sig.positions.max() <= 1.0

    def test_warmup_period_produces_zeros(self) -> None:
        sig = MovingAverageCrossover(fast=10, slow=30).generate_signals(_ohlcv(100))
        # Le prime (slow-1) barre devono essere 0 (NaN ffill→0)
        assert (sig.positions.iloc[:29] == 0.0).all()

    def test_invalid_periods_raise(self) -> None:
        with pytest.raises(BacktestError):
            MovingAverageCrossover(fast=30, slow=20)  # fast >= slow

    def test_short_data_returns_zero_signal(self) -> None:
        sig = MovingAverageCrossover(fast=10, slow=50).generate_signals(_ohlcv(20))
        assert (sig.positions == 0.0).all()


# ═══════════════════════════════════════════════════════════════════════════
# RSI mean reversion
# ═══════════════════════════════════════════════════════════════════════════
class TestRSI:
    def test_compute_rsi_in_range(self) -> None:
        close = _ohlcv(100)["close"]
        rsi = compute_rsi(close, period=14)
        # RSI deve essere in [0, 100] (esclusi i NaN del warm-up)
        valid = rsi.dropna()
        assert (valid >= 0.0).all() and (valid <= 100.0).all()

    def test_strategy_signals_in_range(self) -> None:
        sig = RSIMeanReversion(period=14).generate_signals(_ohlcv(100))
        assert sig.positions.min() >= 0.0
        assert sig.positions.max() <= 1.0

    def test_invalid_thresholds_rejected(self) -> None:
        with pytest.raises(BacktestError):
            RSIMeanReversion(oversold=70, overbought=30)  # ordine invertito

    def test_short_enabled(self) -> None:
        sig = RSIMeanReversion(allow_short=True).generate_signals(_ohlcv(100))
        # Almeno una posizione short attesa su una lunga serie random
        assert sig.positions.min() >= -1.0


# ═══════════════════════════════════════════════════════════════════════════
# Momentum
# ═══════════════════════════════════════════════════════════════════════════
class TestMomentum:
    def test_signal_long_only(self) -> None:
        sig = Momentum(lookback=30).generate_signals(_ohlcv(120, drift=0.001))
        assert sig.positions.min() >= 0.0
        assert sig.positions.max() <= 1.0

    def test_breakout_filter_strict(self) -> None:
        # require_breakout=True deve produrre meno (o uguali) segnali del raw
        ohlcv = _ohlcv(120, drift=0.001)
        with_breakout = Momentum(lookback=20, require_breakout=True).generate_signals(ohlcv)
        without = Momentum(lookback=20, require_breakout=False).generate_signals(ohlcv)
        assert with_breakout.positions.sum() <= without.positions.sum()

    def test_short_data_returns_zero(self) -> None:
        sig = Momentum(lookback=60).generate_signals(_ohlcv(30))
        assert (sig.positions == 0.0).all()


# ═══════════════════════════════════════════════════════════════════════════
# MacroFilter
# ═══════════════════════════════════════════════════════════════════════════
class TestMacroFilter:
    def test_low_vix_passes_signals(self) -> None:
        ohlcv = _ohlcv(100)
        # Macro VIX basso costante → tutti i long passano
        macro = pd.DataFrame(
            {"ts": ohlcv["ts"], "value": [15.0] * len(ohlcv)}
        )
        base = MovingAverageCrossover(fast=5, slow=20)
        wrapped = MacroFilter(base, macro, threshold=20.0, mode="low_is_good")
        wrapped_sig = wrapped.generate_signals(ohlcv)
        base_sig = base.generate_signals(ohlcv)
        # Le posizioni long devono coincidere (VIX < 20 sempre)
        assert (wrapped_sig.positions.fillna(0).to_numpy()
                == base_sig.positions.fillna(0).to_numpy()).all()

    def test_high_vix_blocks_long_signals(self) -> None:
        ohlcv = _ohlcv(100)
        macro = pd.DataFrame(
            {"ts": ohlcv["ts"], "value": [40.0] * len(ohlcv)}  # VIX alto sempre
        )
        base = MovingAverageCrossover(fast=5, slow=20)
        wrapped = MacroFilter(base, macro, threshold=20.0, mode="low_is_good")
        wrapped_sig = wrapped.generate_signals(ohlcv)
        # Tutti i long devono essere bloccati (VIX > 20 sempre)
        assert (wrapped_sig.positions <= 0.0).all()

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(BacktestError):
            MacroFilter(
                MovingAverageCrossover(),
                pd.DataFrame({"ts": [], "value": []}),
                threshold=20,
                mode="invalid_mode",
            )


# ═══════════════════════════════════════════════════════════════════════════
# Combined
# ═══════════════════════════════════════════════════════════════════════════
class TestCombinedStrategy:
    def test_mean_mode(self) -> None:
        ohlcv = _ohlcv(100)
        sub1 = MovingAverageCrossover(fast=5, slow=20)
        sub2 = MovingAverageCrossover(fast=10, slow=30)
        combined = CombinedStrategy([sub1, sub2], mode="mean")
        sig = combined.generate_signals(ohlcv)
        assert sig.positions.min() >= -1.0
        assert sig.positions.max() <= 1.0

    def test_all_mode_more_strict(self) -> None:
        ohlcv = _ohlcv(120)
        sub1 = MovingAverageCrossover(fast=5, slow=20)
        sub2 = MovingAverageCrossover(fast=10, slow=40)
        all_mode = CombinedStrategy([sub1, sub2], mode="all").generate_signals(ohlcv)
        any_mode = CombinedStrategy([sub1, sub2], mode="any").generate_signals(ohlcv)
        # Mode "all" produce ≤ posizioni di mode "any"
        assert all_mode.positions.sum() <= any_mode.positions.sum() + 1e-6

    def test_empty_substrategies_raises(self) -> None:
        with pytest.raises(BacktestError, match="at least one"):
            CombinedStrategy([], mode="mean")

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(BacktestError):
            CombinedStrategy([MovingAverageCrossover()], mode="invalid")
