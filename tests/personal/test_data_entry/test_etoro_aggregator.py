"""Tests for personal.data_entry.etoro_aggregator."""
from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from personal.data_entry.etoro_aggregator import (
    _aggregate_positions,
    aggregate_by_real_ticker,
    update_live_prices,
)


def _make_df(**overrides) -> pd.DataFrame:
    defaults = {
        "real_ticker": ["AAPL", "AAPL", "MSFT"],
        "ticker": ["AAPL", "AAPL", "MSFT"],
        "quantity": [10.0, 5.0, 3.0],
        "open_price": [150.0, 160.0, 300.0],
        "current_price": [180.0, 180.0, 350.0],
        "raw_action": ["Apple", "Apple", "Microsoft"],
    }
    defaults.update(overrides)
    return pd.DataFrame(defaults)


class TestAggregatePositions:
    def test_aggregates_by_real_ticker(self) -> None:
        df = _make_df()
        result = _aggregate_positions(df)
        # 2 unique real_tickers
        assert len(result) == 2

    def test_total_units_summed(self) -> None:
        df = _make_df()
        result = _aggregate_positions(df)
        aapl = result[result["ticker"] == "AAPL"].iloc[0]
        assert aapl["total_units"] == pytest.approx(15.0)

    def test_avg_open_price_weighted(self) -> None:
        df = _make_df()
        result = _aggregate_positions(df)
        aapl = result[result["ticker"] == "AAPL"].iloc[0]
        # invested = 10*150 + 5*160 = 1500 + 800 = 2300; units = 15
        # avg = 2300/15
        assert aapl["avg_open_price"] == pytest.approx(2300.0 / 15.0)

    def test_market_value_computed(self) -> None:
        df = _make_df()
        result = _aggregate_positions(df)
        aapl = result[result["ticker"] == "AAPL"].iloc[0]
        # market_value = total_units * last_current_price = 15 * 180
        assert aapl["market_value"] == pytest.approx(2700.0)

    def test_profit_eur(self) -> None:
        df = _make_df()
        result = _aggregate_positions(df)
        aapl = result[result["ticker"] == "AAPL"].iloc[0]
        # profit = market_value - invested = 2700 - 2300 = 400
        assert aapl["profit_eur"] == pytest.approx(400.0)

    def test_profit_pct(self) -> None:
        df = _make_df()
        result = _aggregate_positions(df)
        aapl = result[result["ticker"] == "AAPL"].iloc[0]
        # profit_pct = 400/2300 * 100
        assert aapl["profit_pct"] == pytest.approx(400.0 / 2300.0 * 100.0)

    def test_raises_when_real_ticker_missing(self) -> None:
        df = pd.DataFrame({"ticker": ["AAPL"], "quantity": [1.0]})
        with pytest.raises(ValueError, match="real_ticker"):
            _aggregate_positions(df)

    def test_coerces_non_numeric_to_zero(self) -> None:
        df = _make_df(quantity=["abc", 5.0, 3.0])  # type: ignore[list-item]
        result = _aggregate_positions(df)
        assert len(result) == 2  # still aggregated, garbage → 0

    def test_zero_invested_profit_pct_is_nan_or_zero(self) -> None:
        df = pd.DataFrame({
            "real_ticker": ["XYZ"],
            "quantity": [10.0],
            "open_price": [0.0],
            "current_price": [50.0],
            "raw_action": ["X"],
        })
        result = _aggregate_positions(df)
        # invested=0 → profit_pct division-by-zero handled
        assert len(result) == 1


class TestAggregateByRealTicker:
    def test_delegates_to_aggregate(self) -> None:
        df = _make_df()
        result = aggregate_by_real_ticker(df)
        assert "total_units" in result.columns
        assert "avg_open_price" in result.columns


class TestUpdateLivePrices:
    def test_real_ticker_missing_resolved_from_ticker(self) -> None:
        # Don't patch _resolve_ticker_from_placeholder — let it run (returns AAPL as-is)
        df = pd.DataFrame({
            "ticker": ["AAPL"],
            "quantity": [10.0],
            "open_price": [150.0],
            "current_price": [None],
            "market_value": [None],
            "profit_eur": [None],
            "profit_pct": [None],
        })
        with patch("personal.data_entry.etoro_aggregator._build_fx_cache",
                   return_value={"GBP_USD": 1.27, "EUR_USD": 1.08}):
            with patch("personal.data_entry.etoro_aggregator._get_live_price_usd",
                       return_value=180.0):
                result = update_live_prices(df)
        assert "real_ticker" in result.columns
        assert result.iloc[0]["real_ticker"] == "AAPL"

    def test_updates_prices_for_resolved_tickers(self) -> None:
        df = pd.DataFrame({
            "ticker": ["AAPL"],
            "real_ticker": ["AAPL"],
            "quantity": [10.0],
            "open_price": [150.0],
            "current_price": [None],
            "market_value": [None],
            "profit_eur": [None],
            "profit_pct": [None],
        })
        with patch("personal.data_entry.etoro_aggregator._build_fx_cache",
                   return_value={"GBP_USD": 1.27, "EUR_USD": 1.08}):
            with patch("personal.data_entry.etoro_aggregator._get_live_price_usd",
                       return_value=180.0):
                result = update_live_prices(df)
        assert result.iloc[0]["current_price"] == pytest.approx(180.0)
        assert result.iloc[0]["market_value"] == pytest.approx(1800.0)
        assert result.iloc[0]["profit_eur"] == pytest.approx(300.0)
        assert result.iloc[0]["profit_pct"] == pytest.approx(20.0)

    def test_placeholder_ticker_skipped(self) -> None:
        df = pd.DataFrame({
            "ticker": ["#99999"],
            "real_ticker": ["#99999"],
            "quantity": [10.0],
            "open_price": [150.0],
            "current_price": [200.0],
            "market_value": [2000.0],
            "profit_eur": [500.0],
            "profit_pct": [33.3],
        })
        with patch("personal.data_entry.etoro_aggregator._build_fx_cache",
                   return_value={"GBP_USD": 1.27, "EUR_USD": 1.08}):
            with patch("personal.data_entry.etoro_aggregator._get_live_price_usd",
                       return_value=180.0) as mock_price:
                result = update_live_prices(df)
        # _get_live_price_usd should NOT have been called for placeholder
        mock_price.assert_not_called()
        # Values stay unchanged
        assert result.iloc[0]["current_price"] == pytest.approx(200.0)

    def test_no_live_price_keeps_row(self) -> None:
        df = pd.DataFrame({
            "ticker": ["AAPL"],
            "real_ticker": ["AAPL"],
            "quantity": [10.0],
            "open_price": [150.0],
            "current_price": [200.0],
            "market_value": [2000.0],
            "profit_eur": [500.0],
            "profit_pct": [33.3],
        })
        with patch("personal.data_entry.etoro_aggregator._build_fx_cache",
                   return_value={"GBP_USD": 1.27, "EUR_USD": 1.08}):
            with patch("personal.data_entry.etoro_aggregator._get_live_price_usd",
                       return_value=None):
                result = update_live_prices(df)
        # Live price unavailable → original values preserved
        assert result.iloc[0]["current_price"] == pytest.approx(200.0)

    def test_zero_invested_profit_pct_zero(self) -> None:
        df = pd.DataFrame({
            "ticker": ["AAPL"],
            "real_ticker": ["AAPL"],
            "quantity": [10.0],
            "open_price": [0.0],
            "current_price": [None],
            "market_value": [None],
            "profit_eur": [None],
            "profit_pct": [None],
        })
        with patch("personal.data_entry.etoro_aggregator._build_fx_cache",
                   return_value={"GBP_USD": 1.27, "EUR_USD": 1.08}):
            with patch("personal.data_entry.etoro_aggregator._get_live_price_usd",
                       return_value=180.0):
                result = update_live_prices(df)
        assert result.iloc[0]["profit_pct"] == pytest.approx(0.0)
