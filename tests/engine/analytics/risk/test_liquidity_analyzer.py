"""Tests for LiquidityAnalyzer."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.analytics.risk.liquidity_analyzer import (
    LiquidityAnalyzer,
    LiquidityResult,
    ILLIQUID_THRESHOLD_DAYS,
    PARTICIPATION_RATE,
)


def _make_volume_price(
    n: int = 60,
    daily_volume: float = 1_000_000.0,
    price: float = 50.0,
    seed: int = 42,
) -> tuple[pd.Series, pd.Series]:
    """Crea serie volume e prezzo con valori costanti + rumore."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="B", tz="UTC")
    vol = pd.Series(
        daily_volume * (1 + rng.normal(0, 0.05, n)).clip(0.1),
        index=dates,
    )
    prc = pd.Series(
        price * (1 + rng.normal(0, 0.01, n)).clip(0.01),
        index=dates,
    )
    return vol, prc


class TestLiquidityAnalyzer:
    """Test suite per LiquidityAnalyzer."""

    def test_analyze_position_returns_result(self) -> None:
        """analyze_position() restituisce LiquidityResult."""
        vol, prc = _make_volume_price()
        result = LiquidityAnalyzer().analyze_position("AAPL", 100_000.0, vol, prc)
        assert isinstance(result, LiquidityResult)

    def test_result_fields(self) -> None:
        """LiquidityResult ha tutti i campi attesi."""
        vol, prc = _make_volume_price()
        result = LiquidityAnalyzer().analyze_position("MSFT", 50_000.0, vol, prc)
        assert result.ticker == "MSFT"
        assert result.position_usd == pytest.approx(50_000.0)
        assert result.adtv_usd > 0
        assert result.adtv_shares > 0
        assert result.days_to_liquidate >= 0
        assert 0.0 <= result.liquidity_score <= 1.0
        assert isinstance(result.is_illiquid, bool)

    def test_high_volume_low_days(self) -> None:
        """Alto volume → basso days_to_liquidate."""
        vol_high, prc = _make_volume_price(daily_volume=10_000_000.0, price=100.0)
        result = LiquidityAnalyzer().analyze_position("TICK", 50_000.0, vol_high, prc)
        # ADTV = 10M × $100 = $1B/day, partecipation 20% = $200M/day
        # 50K / 200M = 0.00025 giorni — molto liquido
        assert result.days_to_liquidate < 1.0
        assert result.is_illiquid is False

    def test_low_volume_high_days(self) -> None:
        """Basso volume → alto days_to_liquidate → is_illiquid=True."""
        vol_low, prc = _make_volume_price(daily_volume=100.0, price=10.0)
        result = LiquidityAnalyzer().analyze_position("ILLIQ", 1_000_000.0, vol_low, prc)
        # ADTV = 100 × $10 = $1000/day, 20% = $200/day
        # 1M / 200 = 5000 giorni — illiquido
        assert result.days_to_liquidate > ILLIQUID_THRESHOLD_DAYS
        assert result.is_illiquid is True

    def test_liquidity_score_high_volume(self) -> None:
        """Score vicino a 1.0 per asset molto liquidi."""
        vol_high, prc = _make_volume_price(daily_volume=100_000_000.0, price=200.0)
        result = LiquidityAnalyzer().analyze_position("SPY", 10_000.0, vol_high, prc)
        assert result.liquidity_score > 0.9

    def test_liquidity_score_low_volume(self) -> None:
        """Score vicino a 0.0 per asset illiquidi."""
        vol_low, prc = _make_volume_price(daily_volume=10.0, price=5.0)
        result = LiquidityAnalyzer().analyze_position("NANO", 500_000.0, vol_low, prc)
        assert result.liquidity_score < 0.2

    def test_analyze_portfolio_returns_list(self) -> None:
        """analyze_portfolio() restituisce lista di LiquidityResult."""
        vol1, prc1 = _make_volume_price(daily_volume=1_000_000.0)
        vol2, prc2 = _make_volume_price(daily_volume=500_000.0, seed=99)
        positions = {"AAPL": 100_000.0, "GOOGL": 200_000.0}
        volume_data = {"AAPL": vol1, "GOOGL": vol2}
        price_data = {"AAPL": prc1, "GOOGL": prc2}
        results = LiquidityAnalyzer().analyze_portfolio(positions, volume_data, price_data)
        assert len(results) == 2
        tickers = {r.ticker for r in results}
        assert "AAPL" in tickers
        assert "GOOGL" in tickers

    def test_analyze_portfolio_missing_data(self) -> None:
        """Asset con dati mancanti → is_illiquid=True nel risultato."""
        vol1, prc1 = _make_volume_price()
        positions = {"AAPL": 100_000.0, "UNKNOWN": 50_000.0}
        volume_data = {"AAPL": vol1}
        price_data = {"AAPL": prc1}
        results = LiquidityAnalyzer().analyze_portfolio(positions, volume_data, price_data)
        by_ticker = {r.ticker: r for r in results}
        assert by_ticker["UNKNOWN"].is_illiquid is True

    def test_portfolio_days_90pct(self) -> None:
        """portfolio_days_90pct restituisce un valore >= 0."""
        vol1, prc1 = _make_volume_price(daily_volume=1_000_000.0)
        vol2, prc2 = _make_volume_price(daily_volume=100.0, seed=99)
        positions = {"LIQ": 100_000.0, "ILLIQ": 50_000.0}
        volume_data = {"LIQ": vol1, "ILLIQ": vol2}
        price_data = {"LIQ": prc1, "ILLIQ": prc2}
        results = LiquidityAnalyzer().analyze_portfolio(positions, volume_data, price_data)
        days = LiquidityAnalyzer().portfolio_days_90pct(results)
        assert days >= 0.0

    def test_portfolio_days_90pct_empty(self) -> None:
        """portfolio_days_90pct([]) restituisce 0.0."""
        assert LiquidityAnalyzer().portfolio_days_90pct([]) == 0.0

    def test_empty_volume_series(self) -> None:
        """Serie vuota → is_illiquid=True, days_to_liquidate=inf."""
        empty_vol = pd.Series(dtype=float)
        empty_prc = pd.Series(dtype=float)
        result = LiquidityAnalyzer().analyze_position("EMPTY", 1000.0, empty_vol, empty_prc)
        assert result.is_illiquid is True
        assert result.liquidity_score == 0.0
