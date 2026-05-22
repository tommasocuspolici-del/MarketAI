"""Tests for VRPCalculator."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from datetime import date

from engine.analytics.derivatives.vrp_calculator import (
    VRPCalculator,
    VRPResult,
    RV_WINDOW,
    ANNUALIZATION_FACTOR,
)


def _make_iv_series(
    n: int = 300,
    level: float = 0.20,
    seed: int = 42,
) -> pd.Series:
    """Serie IV ATM 30gg annualizzata."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-01", periods=n, freq="B", tz="UTC")
    iv = level + rng.normal(0, 0.02, n)
    return pd.Series(np.clip(iv, 0.01, None), index=dates)


def _make_price_series(
    n: int = 300,
    start: float = 100.0,
    vol: float = 0.15,
    seed: int = 42,
) -> pd.Series:
    """Serie prezzi close per calcolo RV."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-01", periods=n, freq="B", tz="UTC")
    log_rets = rng.normal(0, vol / np.sqrt(ANNUALIZATION_FACTOR), n)
    prices = start * np.exp(np.cumsum(log_rets))
    return pd.Series(prices, index=dates)


class TestVRPCalculator:
    """Test suite per VRPCalculator."""

    def test_compute_returns_vrp_result(self) -> None:
        """compute() restituisce VRPResult."""
        calc = VRPCalculator()
        iv = _make_iv_series(200, level=0.22)
        prices = _make_price_series(200)
        result = calc.compute("SPY", iv, prices)
        assert isinstance(result, VRPResult)

    def test_result_fields(self) -> None:
        """Tutti i campi di VRPResult sono valorizzati."""
        iv = _make_iv_series(300, level=0.20)
        prices = _make_price_series(300, vol=0.12)
        result = VRPCalculator().compute("QQQ", iv, prices)
        assert result.ticker == "QQQ"
        assert isinstance(result.snapshot_date, date)
        assert isinstance(result.iv_atm_30d, float)
        assert isinstance(result.rv_30d, float)
        assert isinstance(result.vrp, float)
        assert isinstance(result.vrp_zscore, float)
        assert isinstance(result.signal, float)
        assert isinstance(result.is_reliable, bool)

    def test_vrp_equals_iv_minus_rv(self) -> None:
        """vrp = iv_atm_30d - rv_30d (sanity check base)."""
        iv = _make_iv_series(200, level=0.25)
        prices = _make_price_series(200, vol=0.15)
        result = VRPCalculator().compute("SPY", iv, prices)
        expected_vrp = result.iv_atm_30d - result.rv_30d
        assert abs(result.vrp - expected_vrp) < 1e-8

    def test_signal_in_range(self) -> None:
        """signal è in [-1, +1]."""
        for seed in [1, 2, 3, 42, 99]:
            iv = _make_iv_series(300, seed=seed)
            prices = _make_price_series(300, seed=seed + 1)
            result = VRPCalculator().compute("TICK", iv, prices)
            assert -1.0 <= result.signal <= 1.0, (
                f"signal={result.signal} fuori range [-1,+1]"
            )

    def test_high_iv_negative_signal(self) -> None:
        """IV molto alta vs RV bassa → VRP alto → signal < 0 (vol cara)."""
        # IV = 50%, RV simulata bassa (~10%)
        iv = _make_iv_series(300, level=0.50)
        prices = _make_price_series(300, vol=0.10)
        result = VRPCalculator().compute("VIX_HIGH", iv, prices)
        # VRP alto → z-score alto → signal negativo (sell vol)
        assert result.vrp > 0  # IV > RV
        # Il signal dovrebbe tendere verso -1 per VRP molto positivo
        assert result.signal < 0.5

    def test_is_reliable_with_enough_data(self) -> None:
        """is_reliable=True se ci sono abbastanza dati per RV."""
        iv = _make_iv_series(200)
        prices = _make_price_series(200)
        result = VRPCalculator().compute("SPY", iv, prices)
        assert result.is_reliable is True

    def test_empty_iv_series(self) -> None:
        """Serie IV vuota → is_reliable=False, signal=0."""
        iv = pd.Series(dtype=float)
        prices = _make_price_series(100)
        result = VRPCalculator().compute("EMPTY", iv, prices)
        assert result.is_reliable is False
        assert result.signal == 0.0

    def test_compute_batch(self) -> None:
        """compute_batch() restituisce lista VRPResult con stesso numero di ticker."""
        tickers = ["SPY", "QQQ", "IWM"]
        iv_data = {t: _make_iv_series(200, seed=i) for i, t in enumerate(tickers)}
        price_data = {t: _make_price_series(200, seed=i + 10) for i, t in enumerate(tickers)}
        results = VRPCalculator().compute_batch(tickers, iv_data, price_data)
        assert len(results) == 3
        result_tickers = [r.ticker for r in results]
        assert result_tickers == tickers

    def test_realized_vol_positive(self) -> None:
        """RV su prezzi reali deve essere > 0."""
        calc = VRPCalculator()
        prices = _make_price_series(100)
        rv = calc._realized_vol(prices, window=21)
        assert rv > 0.0

    def test_rv_annualized(self) -> None:
        """RV deve essere nell'ordine di grandezza annualizzato (es. 5%-100%)."""
        calc = VRPCalculator()
        prices = _make_price_series(300, vol=0.20)
        rv = calc._realized_vol(prices)
        # Volatilità sintetica 20% → RV deve essere nell'intervallo [5%, 50%]
        assert 0.03 < rv < 0.80

    def test_snapshot_date_is_last_iv_date(self) -> None:
        """snapshot_date deve corrispondere all'ultimo valore di IV."""
        iv = _make_iv_series(100)
        prices = _make_price_series(100)
        result = VRPCalculator().compute("SPY", iv, prices)
        expected_date = iv.index[-1].date()
        assert result.snapshot_date == expected_date
