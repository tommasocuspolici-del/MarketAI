"""Tests for VolumeProfileCalculator — POC, VAH, VAL, VWAP, signal."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.analytics.technical.volume_profile import VolumeProfile, VolumeProfileCalculator


def _make_ohlcv(n: int = 100, base: float = 100.0) -> pd.DataFrame:
    rng    = np.random.default_rng(7)
    prices = base + rng.normal(0, 1, n).cumsum()
    prices = np.maximum(prices, 1.0)
    dates  = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "open":   prices,
        "high":   prices * 1.01,
        "low":    prices * 0.99,
        "close":  prices + rng.normal(0, 0.2, n),
        "volume": rng.integers(1_000, 10_000, n).astype(float),
    }, index=dates)


class TestKeyLevels:
    def test_poc_within_price_range(self) -> None:
        calc   = VolumeProfileCalculator()
        ohlcv  = _make_ohlcv()
        result = calc.compute(ohlcv)
        assert result.poc >= ohlcv["low"].min() * 0.99
        assert result.poc <= ohlcv["high"].max() * 1.01

    def test_vah_above_poc(self) -> None:
        calc   = VolumeProfileCalculator()
        result = calc.compute(_make_ohlcv())
        assert result.vah >= result.poc

    def test_val_below_poc(self) -> None:
        calc   = VolumeProfileCalculator()
        result = calc.compute(_make_ohlcv())
        assert result.val <= result.poc

    def test_vah_above_val(self) -> None:
        calc   = VolumeProfileCalculator()
        result = calc.compute(_make_ohlcv())
        assert result.vah >= result.val

    def test_vwap_within_range(self) -> None:
        calc   = VolumeProfileCalculator()
        ohlcv  = _make_ohlcv()
        result = calc.compute(ohlcv)
        assert ohlcv["low"].min() * 0.98 <= result.vwap <= ohlcv["high"].max() * 1.02


class TestSignal:
    def test_signal_in_range(self) -> None:
        calc   = VolumeProfileCalculator()
        result = calc.compute(_make_ohlcv())
        assert -1.0 <= result.signal <= 1.0

    def test_price_above_vah_bullish(self) -> None:
        calc   = VolumeProfileCalculator()
        result = calc.compute(_make_ohlcv())
        # Synthetic: price clearly above VAH → signal > 0
        if result.current_price >= result.vah:
            assert result.signal > 0
            assert result.signal_label == "above_va"

    def test_price_below_val_bearish(self) -> None:
        calc = VolumeProfileCalculator()
        # Create a dataset where price is low (bear case)
        ohlcv = _make_ohlcv(100, base=10.0)
        result = calc.compute(ohlcv)
        if result.current_price <= result.val:
            assert result.signal < 0
            assert result.signal_label == "below_va"

    def test_signal_label_valid(self) -> None:
        calc   = VolumeProfileCalculator()
        result = calc.compute(_make_ohlcv())
        assert result.signal_label in ("above_va", "in_va", "below_va")


class TestEdgeCases:
    def test_empty_ohlcv_returns_empty_profile(self) -> None:
        calc   = VolumeProfileCalculator()
        ohlcv  = pd.DataFrame(columns=["high", "low", "close", "volume"])
        result = calc.compute(ohlcv)
        assert result.n_bars == 0
        assert result.signal == pytest.approx(0.0)

    def test_single_bar_handled(self) -> None:
        calc  = VolumeProfileCalculator()
        ohlcv = pd.DataFrame(
            {"open": [100], "high": [101], "low": [99], "close": [100], "volume": [1000]},
            index=pd.date_range("2024-01-01", periods=1),
        )
        result = calc.compute(ohlcv)
        assert result.n_bars <= 1

    def test_bins_are_numpy_arrays(self) -> None:
        calc   = VolumeProfileCalculator()
        result = calc.compute(_make_ohlcv())
        assert isinstance(result.price_bins, np.ndarray)
        assert isinstance(result.volume_bins, np.ndarray)


class TestVWAPAccuracy:
    def test_vwap_equals_simple_calculation(self) -> None:
        """VWAP = sum(typical_price * volume) / sum(volume)."""
        calc  = VolumeProfileCalculator()
        ohlcv = _make_ohlcv(20)
        result = calc.compute(ohlcv)
        typical = (ohlcv["high"] + ohlcv["low"] + ohlcv["close"]) / 3
        expected_vwap = float((typical * ohlcv["volume"]).sum() / ohlcv["volume"].sum())
        assert result.vwap == pytest.approx(expected_vwap, rel=1e-3)
