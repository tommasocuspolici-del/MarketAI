from __future__ import annotations

import math
import pytest
from shared.exceptions import MarketAIError
import numpy as np
import pandas as pd

from engine.alpha_generation.backtest_engine.capacity_estimator import (
    CapacityEstimator,
    CapacityResult,
    PARTICIPATION_RATE,
)


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

class TestInstantiation:
    def test_default_participation_rate(self) -> None:
        est = CapacityEstimator()
        assert est._participation_rate == PARTICIPATION_RATE
        assert est._participation_rate == 0.05

    def test_custom_participation_rate(self) -> None:
        est = CapacityEstimator(participation_rate=0.10)
        assert est._participation_rate == 0.10

    def test_invalid_participation_rate_zero(self) -> None:
        with pytest.raises((ValueError, MarketAIError)):
            CapacityEstimator(participation_rate=0.0)

    def test_invalid_participation_rate_negative(self) -> None:
        with pytest.raises((ValueError, MarketAIError)):
            CapacityEstimator(participation_rate=-0.1)

    def test_participation_rate_one_is_valid(self) -> None:
        est = CapacityEstimator(participation_rate=1.0)
        assert est._participation_rate == 1.0


# ---------------------------------------------------------------------------
# estimate — single asset
# ---------------------------------------------------------------------------

class TestEstimate:
    def test_returns_capacity_result(self) -> None:
        est = CapacityEstimator()
        result = est.estimate("SPY", adtv_usd=1_000_000, daily_turnover=0.10)
        assert isinstance(result, CapacityResult)

    def test_capacity_formula(self) -> None:
        """capacity_usd = adtv_usd * participation_rate / daily_turnover"""
        est = CapacityEstimator(participation_rate=0.05)
        adtv = 1_000_000
        turnover = 0.10
        result = est.estimate("SPY", adtv_usd=adtv, daily_turnover=turnover)
        expected = adtv * 0.05 / turnover  # = 500_000
        assert math.isclose(result.capacity_usd, expected, rel_tol=1e-9)

    def test_no_warning_when_capital_low(self) -> None:
        est = CapacityEstimator(participation_rate=0.05)
        # capacity = 1_000_000 * 0.05 / 0.10 = 500_000
        # 10% of capacity = 50_000; capital = 10_000 < 50_000 → no warning
        result = est.estimate("SPY", adtv_usd=1_000_000, daily_turnover=0.10, current_capital_usd=10_000)
        assert result.capacity_warning is False

    def test_warning_when_capital_high(self) -> None:
        est = CapacityEstimator(participation_rate=0.05)
        # capacity = 500_000; 10% = 50_000; capital = 100_000 > 50_000 → warning
        result = est.estimate("SPY", adtv_usd=1_000_000, daily_turnover=0.10, current_capital_usd=100_000)
        assert result.capacity_warning is True

    def test_zero_capital_no_warning(self) -> None:
        est = CapacityEstimator()
        result = est.estimate("AAPL", adtv_usd=500_000, daily_turnover=0.05, current_capital_usd=0.0)
        assert result.capacity_warning is False

    def test_ticker_stored(self) -> None:
        est = CapacityEstimator()
        result = est.estimate("MSFT", adtv_usd=2_000_000, daily_turnover=0.05)
        assert result.ticker == "MSFT"

    def test_adtv_stored(self) -> None:
        est = CapacityEstimator()
        result = est.estimate("MSFT", adtv_usd=2_000_000, daily_turnover=0.05)
        assert result.adtv_usd == 2_000_000

    def test_negative_adtv_raises(self) -> None:
        est = CapacityEstimator()
        with pytest.raises((ValueError, MarketAIError)):
            est.estimate("SPY", adtv_usd=-100, daily_turnover=0.05)

    def test_invalid_turnover_raises(self) -> None:
        est = CapacityEstimator()
        with pytest.raises((ValueError, MarketAIError)):
            est.estimate("SPY", adtv_usd=100_000, daily_turnover=1.5)

    def test_zero_turnover_returns_infinite_capacity(self) -> None:
        est = CapacityEstimator()
        result = est.estimate("SPY", adtv_usd=1_000_000, daily_turnover=0.0, current_capital_usd=1_000_000)
        assert result.capacity_usd == float("inf")
        # No warning for infinite capacity
        assert result.capacity_warning is False


# ---------------------------------------------------------------------------
# estimate_portfolio
# ---------------------------------------------------------------------------

class TestEstimatePortfolio:
    def test_returns_dict(self) -> None:
        est = CapacityEstimator()
        positions = {"SPY": 1_000_000, "QQQ": 800_000}
        result = est.estimate_portfolio(positions, daily_turnover=0.05, current_capital_usd=50_000)
        assert isinstance(result, dict)

    def test_one_entry_per_ticker(self) -> None:
        est = CapacityEstimator()
        positions = {"SPY": 1_000_000, "QQQ": 800_000, "AAPL": 500_000}
        result = est.estimate_portfolio(positions, daily_turnover=0.05, current_capital_usd=30_000)
        assert set(result.keys()) == {"SPY", "QQQ", "AAPL"}

    def test_empty_positions_returns_empty(self) -> None:
        est = CapacityEstimator()
        result = est.estimate_portfolio({}, daily_turnover=0.05, current_capital_usd=10_000)
        assert result == {}

    def test_each_value_is_capacity_result(self) -> None:
        est = CapacityEstimator()
        positions = {"SPY": 1_000_000, "GLD": 400_000}
        result = est.estimate_portfolio(positions, daily_turnover=0.10, current_capital_usd=20_000)
        for ticker, cap in result.items():
            assert isinstance(cap, CapacityResult)
            assert cap.ticker == ticker
