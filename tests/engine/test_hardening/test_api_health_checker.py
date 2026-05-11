"""Test del ApiHealthChecker (v7.1.1).

Test mockati: non vogliamo dipendere da connessione internet o API key
nei test unitari. Testiamo la logica di classificazione degli stati.
"""
from __future__ import annotations

import io
import json
from unittest import mock
from urllib.error import HTTPError, URLError

import pytest

from engine.market_data.hardening.api_health_checker import (
    ApiHealthChecker,
    ApiSourceStatus,
    ApiState,
)


# ====================================================== ApiSourceStatus
def test_emoji_for_each_state() -> None:
    """Ogni stato ha un emoji distintivo."""
    s_online = ApiSourceStatus("X", ApiState.ONLINE, 100.0, "ok", True, 0.0)
    s_offline = ApiSourceStatus("X", ApiState.OFFLINE, None, "err", True, 0.0)
    s_no_key = ApiSourceStatus("X", ApiState.NO_API_KEY, None, "no key", False, 0.0)
    s_degraded = ApiSourceStatus("X", ApiState.DEGRADED, 200.0, "rl", True, 0.0)

    # Tutti emoji diversi
    emojis = {s_online.emoji, s_offline.emoji, s_no_key.emoji, s_degraded.emoji}
    assert len(emojis) == 4

    # Sanity check sui simboli
    assert s_online.emoji == "✅"
    assert s_offline.emoji == "❌"
    assert s_no_key.emoji == "🔑"


def test_state_label_format() -> None:
    """state_label combina emoji + nome stato."""
    s = ApiSourceStatus("FRED", ApiState.ONLINE, 50.0, "ok", True, 0.0)
    assert "ONLINE" in s.state_label
    assert "✅" in s.state_label


# =========================================== check_fred — no API key
def test_fred_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Senza FRED_API_KEY, FRED ritorna NO_API_KEY senza fare HTTP."""
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    checker = ApiHealthChecker()
    result = checker.check_fred()
    assert result.state == ApiState.NO_API_KEY
    assert result.has_api_key is False
    assert result.latency_ms is None
    assert "FRED_API_KEY" in result.message


def test_alpha_vantage_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Senza ALPHA_VANTAGE_KEY, AV ritorna NO_API_KEY."""
    monkeypatch.delenv("ALPHA_VANTAGE_KEY", raising=False)
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    checker = ApiHealthChecker()
    result = checker.check_alpha_vantage()
    assert result.state == ApiState.NO_API_KEY


def test_finnhub_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Senza FINNHUB_API_KEY, Finnhub ritorna NO_API_KEY."""
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    checker = ApiHealthChecker()
    result = checker.check_finnhub()
    assert result.state == ApiState.NO_API_KEY


# =========================================== HTTP success cases
def _make_mock_response(body: str, status: int = 200) -> mock.MagicMock:
    """Helper: costruisce una mock HTTPResponse."""
    resp = mock.MagicMock()
    resp.status = status
    resp.read.return_value = body.encode("utf-8")
    resp.__enter__ = mock.MagicMock(return_value=resp)
    resp.__exit__ = mock.MagicMock(return_value=False)
    return resp


def test_yfinance_online_success() -> None:
    """Body con 'chart' e 'result' = ONLINE."""
    body = json.dumps({"chart": {"result": [{"meta": {"symbol": "SPY"}}]}})
    checker = ApiHealthChecker()
    with mock.patch(
        "engine.market_data.hardening.api_health_checker.urllib.request.urlopen",
        return_value=_make_mock_response(body),
    ):
        result = checker.check_yfinance()
    assert result.state == ApiState.ONLINE
    assert result.latency_ms is not None
    assert result.latency_ms >= 0


def test_alpha_vantage_rate_limited_returns_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AV con body 'Information' = DEGRADED (rate limit)."""
    monkeypatch.setenv("ALPHA_VANTAGE_KEY", "FAKE_KEY")
    body = json.dumps(
        {"Information": "Standard API rate limit reached..."}
    )
    checker = ApiHealthChecker()
    with mock.patch(
        "engine.market_data.hardening.api_health_checker.urllib.request.urlopen",
        return_value=_make_mock_response(body),
    ):
        result = checker.check_alpha_vantage()
    assert result.state == ApiState.DEGRADED
    assert "Information" in result.message or "Rate" in result.message.lower() or "rate" in result.message.lower()


def test_alpha_vantage_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """AV con body 'Global Quote' = ONLINE."""
    monkeypatch.setenv("ALPHA_VANTAGE_KEY", "FAKE_KEY")
    body = json.dumps({"Global Quote": {"01. symbol": "SPY"}})
    checker = ApiHealthChecker()
    with mock.patch(
        "engine.market_data.hardening.api_health_checker.urllib.request.urlopen",
        return_value=_make_mock_response(body),
    ):
        result = checker.check_alpha_vantage()
    assert result.state == ApiState.ONLINE


# =========================================== HTTP error cases
def test_http_429_returns_degraded() -> None:
    """HTTP 429 (rate limit) = DEGRADED, non OFFLINE."""
    checker = ApiHealthChecker()
    err = HTTPError(
        url="http://x",
        code=429,
        msg="Too Many Requests",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(b""),
    )
    with mock.patch(
        "engine.market_data.hardening.api_health_checker.urllib.request.urlopen",
        side_effect=err,
    ):
        result = checker.check_yfinance()
    assert result.state == ApiState.DEGRADED
    assert "429" in result.message


def test_http_500_returns_offline() -> None:
    """HTTP 5xx = OFFLINE (provider down)."""
    checker = ApiHealthChecker()
    err = HTTPError(
        url="http://x",
        code=500,
        msg="Internal Server Error",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(b""),
    )
    with mock.patch(
        "engine.market_data.hardening.api_health_checker.urllib.request.urlopen",
        side_effect=err,
    ):
        result = checker.check_yfinance()
    assert result.state == ApiState.OFFLINE
    assert "500" in result.message


def test_http_401_returns_offline_with_clear_message() -> None:
    """HTTP 401 = API key invalida."""
    checker = ApiHealthChecker()
    err = HTTPError(
        url="http://x",
        code=401,
        msg="Unauthorized",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(b""),
    )
    with mock.patch(
        "engine.market_data.hardening.api_health_checker.urllib.request.urlopen",
        side_effect=err,
    ):
        result = checker.check_yfinance()
    assert result.state == ApiState.OFFLINE
    assert "API key" in result.message or "401" in result.message


def test_url_error_returns_offline() -> None:
    """URLError (DNS, connection refused) = OFFLINE."""
    checker = ApiHealthChecker()
    with mock.patch(
        "engine.market_data.hardening.api_health_checker.urllib.request.urlopen",
        side_effect=URLError("Network unreachable"),
    ):
        result = checker.check_yfinance()
    assert result.state == ApiState.OFFLINE
    assert "Network" in result.message or "rete" in result.message.lower()


def test_timeout_returns_offline() -> None:
    """TimeoutError = OFFLINE."""
    checker = ApiHealthChecker(timeout=0.001)
    with mock.patch(
        "engine.market_data.hardening.api_health_checker.urllib.request.urlopen",
        side_effect=TimeoutError("timed out"),
    ):
        result = checker.check_yfinance()
    assert result.state == ApiState.OFFLINE
    assert "imeout" in result.message.lower() or "imeout" in result.message


# =========================================== check_all returns 4 sources
def test_check_all_returns_four_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    """check_all() pinga esattamente 4 sorgenti."""
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("ALPHA_VANTAGE_KEY", raising=False)
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

    checker = ApiHealthChecker()
    body = json.dumps({"chart": {"result": []}})
    with mock.patch(
        "engine.market_data.hardening.api_health_checker.urllib.request.urlopen",
        return_value=_make_mock_response(body),
    ):
        results = checker.check_all()

    assert len(results) == 4
    names = {r.name for r in results}
    assert "Yahoo Finance" in names
    assert any("FRED" in n for n in names)
    assert any("Alpha Vantage" in n for n in names)
    assert "Finnhub" in names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
