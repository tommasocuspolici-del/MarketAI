"""Tests for engine.market_data.websocket_manager — non-network parts only.

Thread, asyncio, and WebSocket connection logic are excluded.
Tests cover: LivePrice dataclass, constructor exceptions, _handle_message,
get_price (staleness), get_all_prices, and singleton helpers.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from engine.market_data.websocket_manager import (
    LivePrice,
    WebSocketStreamManager,
    _PRICE_STALE_SECONDS,
    get_ws_manager,
    reset_ws_manager,
)
from shared.exceptions import ConfigurationError, FeatureDisabledError


def _make_manager() -> WebSocketStreamManager:
    """Instantiate with feature flag forced on."""
    with patch("engine.market_data.websocket_manager.is_enabled", return_value=True):
        return WebSocketStreamManager(api_key="test_key_123")


# ── LivePrice dataclass ───────────────────────────────────────────────────────

class TestLivePrice:
    def test_fields_accessible(self) -> None:
        lp = LivePrice(ticker="AAPL", price=150.0, volume=100.0, timestamp_ms=1714000000, received_at=1.0)
        assert lp.ticker == "AAPL"
        assert lp.price == 150.0
        assert lp.volume == 100.0
        assert lp.timestamp_ms == 1714000000

    def test_frozen_raises_on_mutation(self) -> None:
        lp = LivePrice(ticker="AAPL", price=150.0, volume=100.0, timestamp_ms=1, received_at=1.0)
        with pytest.raises((AttributeError, TypeError)):
            lp.price = 200.0  # type: ignore[misc]

    def test_equality(self) -> None:
        lp1 = LivePrice(ticker="X", price=1.0, volume=2.0, timestamp_ms=3, received_at=4.0)
        lp2 = LivePrice(ticker="X", price=1.0, volume=2.0, timestamp_ms=3, received_at=4.0)
        assert lp1 == lp2


# ── Constructor ───────────────────────────────────────────────────────────────

class TestConstructor:
    def test_feature_disabled_raises(self) -> None:
        with patch("engine.market_data.websocket_manager.is_enabled", return_value=False):
            with pytest.raises(FeatureDisabledError):
                WebSocketStreamManager(api_key="key")

    def test_missing_api_key_raises(self) -> None:
        with patch("engine.market_data.websocket_manager.is_enabled", return_value=True):
            with pytest.raises(ConfigurationError):
                WebSocketStreamManager(api_key="")

    def test_valid_construction_not_running(self) -> None:
        mgr = _make_manager()
        assert mgr.is_running is False

    def test_prices_initially_empty(self) -> None:
        mgr = _make_manager()
        assert mgr.get_all_prices() == {}


# ── _handle_message() ────────────────────────────────────────────────────────

class TestHandleMessage:
    def test_valid_trade_updates_prices(self) -> None:
        mgr = _make_manager()
        raw = '{"type":"trade","data":[{"s":"AAPL","p":150.0,"t":1714000000,"v":100}]}'
        mgr._handle_message(raw)
        with mgr._lock:
            assert "AAPL" in mgr._prices
            assert mgr._prices["AAPL"].price == 150.0

    def test_malformed_json_silently_ignored(self) -> None:
        mgr = _make_manager()
        mgr._handle_message("not json at all!!!")
        assert mgr.get_all_prices() == {}

    def test_non_trade_type_ignored(self) -> None:
        mgr = _make_manager()
        mgr._handle_message('{"type":"ping"}')
        assert mgr.get_all_prices() == {}

    def test_multiple_trades_in_one_message(self) -> None:
        mgr = _make_manager()
        raw = '{"type":"trade","data":[{"s":"AAPL","p":150.0,"t":1,"v":10},{"s":"MSFT","p":300.0,"t":2,"v":20}]}'
        mgr._handle_message(raw)
        prices = mgr.get_all_prices()
        assert "AAPL" in prices
        assert "MSFT" in prices
        assert prices["MSFT"].price == 300.0

    def test_trade_missing_ticker_skipped(self) -> None:
        mgr = _make_manager()
        mgr._handle_message('{"type":"trade","data":[{"p":150.0,"t":1,"v":10}]}')
        assert mgr.get_all_prices() == {}

    def test_trade_missing_price_skipped(self) -> None:
        mgr = _make_manager()
        mgr._handle_message('{"type":"trade","data":[{"s":"AAPL","t":1,"v":10}]}')
        assert mgr.get_all_prices() == {}

    def test_volume_defaults_to_zero_when_missing(self) -> None:
        mgr = _make_manager()
        mgr._handle_message('{"type":"trade","data":[{"s":"AAPL","p":150.0,"t":1}]}')
        with mgr._lock:
            assert mgr._prices["AAPL"].volume == 0.0


# ── get_price() ───────────────────────────────────────────────────────────────

class TestGetPrice:
    def test_unknown_ticker_returns_none(self) -> None:
        mgr = _make_manager()
        assert mgr.get_price("UNKNOWN") is None

    def test_fresh_price_returned(self) -> None:
        mgr = _make_manager()
        mgr._handle_message('{"type":"trade","data":[{"s":"AAPL","p":150.0,"t":1,"v":10}]}')
        lp = mgr.get_price("AAPL")
        assert lp is not None
        assert lp.price == 150.0

    def test_stale_price_returns_none(self) -> None:
        mgr = _make_manager()
        stale = LivePrice(
            ticker="AAPL",
            price=100.0,
            volume=50.0,
            timestamp_ms=1,
            received_at=time.time() - (_PRICE_STALE_SECONDS + 10),
        )
        with mgr._lock:
            mgr._prices["AAPL"] = stale
        assert mgr.get_price("AAPL") is None


# ── get_all_prices() ──────────────────────────────────────────────────────────

class TestGetAllPrices:
    def test_returns_copy_not_original(self) -> None:
        mgr = _make_manager()
        mgr._handle_message('{"type":"trade","data":[{"s":"AAPL","p":150.0,"t":1,"v":10}]}')
        snapshot = mgr.get_all_prices()
        assert "AAPL" in snapshot
        # Mutating the snapshot must not affect internal state
        snapshot["FAKE"] = None  # type: ignore[assignment]
        assert "FAKE" not in mgr._prices

    def test_empty_when_no_messages(self) -> None:
        mgr = _make_manager()
        assert mgr.get_all_prices() == {}


# ── Singleton ─────────────────────────────────────────────────────────────────

class TestSingleton:
    def setup_method(self) -> None:
        reset_ws_manager()

    def teardown_method(self) -> None:
        reset_ws_manager()

    def test_get_ws_manager_disabled_returns_none(self) -> None:
        with patch("engine.market_data.websocket_manager.is_enabled", return_value=False):
            result = get_ws_manager(api_key="key")
        assert result is None

    def test_get_ws_manager_no_key_returns_none(self) -> None:
        with patch("engine.market_data.websocket_manager.is_enabled", return_value=True), \
             patch("os.getenv", return_value=""):
            result = get_ws_manager(api_key=None)
        assert result is None

    def test_reset_clears_instance(self) -> None:
        with patch("engine.market_data.websocket_manager.is_enabled", return_value=True), \
             patch.dict("os.environ", {"FINNHUB_API_KEY": "test_key_abc"}):
            mgr1 = get_ws_manager()
        reset_ws_manager()
        # After reset, calling again with disabled flag returns None
        with patch("engine.market_data.websocket_manager.is_enabled", return_value=False):
            mgr2 = get_ws_manager()
        assert mgr2 is None
