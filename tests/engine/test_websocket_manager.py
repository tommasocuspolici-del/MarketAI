"""Tests for WebSocketStreamManager.

Roadmap v3.0 — Settimana 2.

Tutti i test mockano la connessione WebSocket — nessuna rete reale.
Il focus è su: gestione messaggi, thread-safety, stale detection, feature flag.
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest


# ─── Helper per costruire il manager con flag abilitato ───────────────────────

def _make_manager(monkeypatch):
    """Crea WebSocketStreamManager con flag abilitato e api_key mock."""
    monkeypatch.setenv("FINNHUB_API_KEY", "test_key")
    with patch("engine.market_data.websocket_manager.is_enabled", return_value=True):
        from engine.market_data.websocket_manager import (
            WebSocketStreamManager,
            reset_ws_manager,
        )
        reset_ws_manager()
        return WebSocketStreamManager(api_key="test_key")


# ─── Test: feature flag ───────────────────────────────────────────────────────

def test_raises_if_flag_disabled(monkeypatch) -> None:
    """Costruttore lancia FeatureDisabledError se realtime_websocket è off."""
    with patch("engine.market_data.websocket_manager.is_enabled", return_value=False):
        from engine.market_data.websocket_manager import WebSocketStreamManager
        from shared.exceptions import FeatureDisabledError

        with pytest.raises(FeatureDisabledError):
            WebSocketStreamManager(api_key="dummy")


def test_raises_if_no_api_key(monkeypatch) -> None:
    """Costruttore lancia ConfigurationError se api_key è vuota."""
    with patch("engine.market_data.websocket_manager.is_enabled", return_value=True):
        from engine.market_data.websocket_manager import WebSocketStreamManager
        from shared.exceptions import ConfigurationError

        with pytest.raises(ConfigurationError):
            WebSocketStreamManager(api_key="")


# ─── Test: get_price ──────────────────────────────────────────────────────────

def test_get_price_empty_returns_none(monkeypatch) -> None:
    """get_price su ticker senza dati → None."""
    mgr = _make_manager(monkeypatch)
    assert mgr.get_price("AAPL") is None


def test_get_price_returns_live_price(monkeypatch) -> None:
    """get_price ritorna il prezzo iniettato artificialmente."""
    mgr = _make_manager(monkeypatch)

    from engine.market_data.websocket_manager import LivePrice
    lp = LivePrice(
        ticker="AAPL",
        price=150.0,
        volume=1000.0,
        timestamp_ms=1714000000000,
        received_at=time.time(),
    )
    with mgr._lock:
        mgr._prices["AAPL"] = lp

    result = mgr.get_price("AAPL")
    assert result is not None
    assert result.price == pytest.approx(150.0)


def test_get_price_stale_returns_none(monkeypatch) -> None:
    """Prezzo più vecchio di _PRICE_STALE_SECONDS → None."""
    mgr = _make_manager(monkeypatch)

    from engine.market_data.websocket_manager import LivePrice, _PRICE_STALE_SECONDS
    lp = LivePrice(
        ticker="AAPL",
        price=150.0,
        volume=500.0,
        timestamp_ms=1714000000000,
        received_at=time.time() - _PRICE_STALE_SECONDS - 1,  # scaduto
    )
    with mgr._lock:
        mgr._prices["AAPL"] = lp

    assert mgr.get_price("AAPL") is None


# ─── Test: _handle_message ────────────────────────────────────────────────────

def test_handle_trade_message_updates_price(monkeypatch) -> None:
    """Messaggio trade aggiorna il dict prezzi."""
    mgr = _make_manager(monkeypatch)

    msg = json.dumps({
        "type": "trade",
        "data": [{"s": "AAPL", "p": 155.5, "t": 1714000000000, "v": 200}],
    })
    mgr._handle_message(msg)

    result = mgr.get_price("AAPL")
    assert result is not None
    assert result.price == pytest.approx(155.5)
    assert result.volume == pytest.approx(200.0)


def test_handle_non_trade_message_ignored(monkeypatch) -> None:
    """Messaggi di tipo diverso da 'trade' non aggiornano i prezzi."""
    mgr = _make_manager(monkeypatch)

    msg = json.dumps({"type": "ping"})
    mgr._handle_message(msg)

    assert len(mgr._prices) == 0


def test_handle_invalid_json_does_not_crash(monkeypatch) -> None:
    """JSON malformato → nessuna eccezione."""
    mgr = _make_manager(monkeypatch)
    mgr._handle_message("not-json{{{")  # nessuna eccezione


def test_handle_trade_missing_symbol_skipped(monkeypatch) -> None:
    """Trade senza ticker 's' → skip silenzioso."""
    mgr = _make_manager(monkeypatch)

    msg = json.dumps({
        "type": "trade",
        "data": [{"p": 100.0, "t": 1714000000000}],  # manca 's'
    })
    mgr._handle_message(msg)
    assert len(mgr._prices) == 0


def test_handle_multiple_tickers_in_one_message(monkeypatch) -> None:
    """Un messaggio con più trade aggiorna tutti i ticker."""
    mgr = _make_manager(monkeypatch)

    msg = json.dumps({
        "type": "trade",
        "data": [
            {"s": "AAPL", "p": 150.0, "t": 1000, "v": 100},
            {"s": "MSFT", "p": 300.0, "t": 1000, "v": 50},
        ],
    })
    mgr._handle_message(msg)

    assert mgr.get_price("AAPL") is not None
    assert mgr.get_price("MSFT") is not None
    assert mgr.get_price("MSFT").price == pytest.approx(300.0)


# ─── Test: get_all_prices ─────────────────────────────────────────────────────

def test_get_all_prices_returns_copy(monkeypatch) -> None:
    """get_all_prices ritorna una copia difensiva."""
    mgr = _make_manager(monkeypatch)

    from engine.market_data.websocket_manager import LivePrice
    lp = LivePrice("AAPL", 150.0, 100.0, 1714000000000, time.time())
    with mgr._lock:
        mgr._prices["AAPL"] = lp

    prices = mgr.get_all_prices()
    assert "AAPL" in prices
    # Modifica della copia non altera il dict interno
    prices["NEW"] = lp
    assert "NEW" not in mgr._prices


# ─── Test: singleton ─────────────────────────────────────────────────────────

def test_get_ws_manager_returns_none_if_flag_off(monkeypatch) -> None:
    """get_ws_manager ritorna None se il flag è disabilitato."""
    with patch("engine.market_data.websocket_manager.is_enabled", return_value=False):
        from engine.market_data.websocket_manager import get_ws_manager, reset_ws_manager
        reset_ws_manager()
        assert get_ws_manager() is None


def test_get_ws_manager_returns_none_without_api_key(monkeypatch) -> None:
    """get_ws_manager ritorna None se FINNHUB_API_KEY non è configurata."""
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    with patch("engine.market_data.websocket_manager.is_enabled", return_value=True):
        from engine.market_data.websocket_manager import get_ws_manager, reset_ws_manager
        reset_ws_manager()
        result = get_ws_manager()
        assert result is None
