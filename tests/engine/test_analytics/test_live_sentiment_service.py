"""Tests for engine.analytics.sentiment.live_sentiment_service."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from engine.analytics.sentiment.live_sentiment_service import (
    LiveSentimentService,
    SentimentScores,
)


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_service(key: str = "") -> LiveSentimentService:
    return LiveSentimentService(finnhub_api_key=key)


def _spy_history(n: int = 60) -> pd.Series:
    """Synthetic SPY close prices with realistic up/down moves for RSI computation."""
    import math

    prices = [400.0 + math.sin(i * 0.3) * 10.0 + (i % 3 - 1) * 2.0 for i in range(n)]
    return pd.Series(prices, dtype=float)


# ── SentimentScores ────────────────────────────────────────────────────────

class TestSentimentScores:
    def test_all_none_returns_fallbacks(self) -> None:
        s = SentimentScores()
        fb = {"CNN F&G": 0.3, "Put/Call": -0.2}
        d = s.to_display_dict(fallbacks=fb)
        assert d["CNN F&G"] == 0.3
        assert d["Put/Call"] == -0.2
        assert d["Crypto F&G"] == 0.0  # no fallback → 0

    def test_live_sources_only_non_none(self) -> None:
        s = SentimentScores()
        s.cnn_fg = 0.5
        s.crypto_fg = -0.1
        assert s.live_sources == ["CNN F&G", "Crypto F&G"]

    def test_demo_sources_complement_live(self) -> None:
        s = SentimentScores()
        s.put_call = 0.3
        live = set(s.live_sources)
        demo = set(s.demo_sources)
        all_labels = {"CNN F&G", "Crypto F&G", "Put/Call", "Finnhub",
                      "AAII", "COT", "Insider", "Short Int"}
        assert live | demo == all_labels
        assert live & demo == set()


# ── CNN Fear & Greed ────────────────────────────────────────────────────────

class TestFetchCnnFg:
    def _mock_response(self, json_data: dict) -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = json_data
        resp.raise_for_status.return_value = None
        return resp

    def test_success_fear_and_greed_key(self) -> None:
        svc = _make_service()
        scores = SentimentScores()
        payload = {"fear_and_greed": {"score": 75.0}}

        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.get.return_value = self._mock_response(payload)

            result = svc._fetch_cnn_fg(scores)

        assert result is not None
        assert pytest.approx(result, abs=0.01) == 0.5   # (75/100)*2-1 = 0.5
        assert "CNN F&G" not in scores.errors

    def test_success_top_level_score_key(self) -> None:
        svc = _make_service()
        scores = SentimentScores()
        payload = {"score": 25.0}

        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.get.return_value = self._mock_response(payload)

            result = svc._fetch_cnn_fg(scores)

        assert result is not None
        assert pytest.approx(result, abs=0.01) == -0.5  # (25/100)*2-1 = -0.5

    def test_http_error_returns_none_and_sets_error(self) -> None:
        import requests as req_lib

        svc = _make_service()
        scores = SentimentScores()

        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.get.side_effect = req_lib.HTTPError("418 Unknown")

            result = svc._fetch_cnn_fg(scores)

        assert result is None
        assert "CNN F&G" in scores.errors

    def test_missing_score_field_returns_none(self) -> None:
        svc = _make_service()
        scores = SentimentScores()

        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.get.return_value = self._mock_response({"other": 1})

            result = svc._fetch_cnn_fg(scores)

        assert result is None
        assert "CNN F&G" in scores.errors


# ── Put/Call via yfinance options ──────────────────────────────────────────

class TestFetchPutCall:
    def _mock_chain(self, put_vol: float, call_vol: float) -> MagicMock:
        puts = pd.DataFrame({"volume": [put_vol]})
        calls = pd.DataFrame({"volume": [call_vol]})
        chain = SimpleNamespace(puts=puts, calls=calls)
        return chain

    def test_success_bullish_ratio(self) -> None:
        svc = _make_service()
        scores = SentimentScores()

        mock_ticker = MagicMock()
        mock_ticker.options = ("2025-01-17",)
        mock_ticker.option_chain.return_value = self._mock_chain(60.0, 100.0)  # ratio=0.6 → bullish

        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = svc._fetch_cboe_put_call(scores)

        assert result == 1.0  # 0.6 <= 0.70 → +1
        assert "Put/Call" not in scores.errors

    def test_success_bearish_ratio(self) -> None:
        svc = _make_service()
        scores = SentimentScores()

        mock_ticker = MagicMock()
        mock_ticker.options = ("2025-01-17",)
        mock_ticker.option_chain.return_value = self._mock_chain(150.0, 100.0)  # ratio=1.5 → bearish

        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = svc._fetch_cboe_put_call(scores)

        assert result == -1.0  # 1.5 >= 1.25 → -1
        assert "Put/Call" not in scores.errors

    def test_no_options_dates_returns_none(self) -> None:
        svc = _make_service()
        scores = SentimentScores()

        mock_ticker = MagicMock()
        mock_ticker.options = ()

        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = svc._fetch_cboe_put_call(scores)

        assert result is None
        assert "Put/Call" in scores.errors

    def test_zero_call_volume_returns_none(self) -> None:
        svc = _make_service()
        scores = SentimentScores()

        mock_ticker = MagicMock()
        mock_ticker.options = ("2025-01-17",)
        mock_ticker.option_chain.return_value = self._mock_chain(50.0, 0.0)

        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = svc._fetch_cboe_put_call(scores)

        assert result is None
        assert "Put/Call" in scores.errors


# ── Finnhub / RSI fallback ─────────────────────────────────────────────────

class TestFetchFinnhub:
    def test_finnhub_success(self) -> None:
        svc = _make_service(key="testkey")
        scores = SentimentScores()
        payload = {"sentiment": {"bullishPercent": 0.65, "bearishPercent": 0.20}}

        with patch.object(svc, "_get_json", return_value=payload):
            result = svc._fetch_finnhub(scores)

        assert result is not None
        assert pytest.approx(result, abs=0.001) == 0.45  # 0.65 - 0.20
        assert "Finnhub" not in scores.errors

    def test_finnhub_403_falls_back_to_rsi(self) -> None:
        from urllib.error import HTTPError

        svc = _make_service(key="testkey")
        scores = SentimentScores()

        hist = _spy_history(60)

        with patch.object(svc, "_get_json", side_effect=HTTPError(None, 403, "Forbidden", {}, None)):
            with patch("yfinance.Ticker") as mock_yf:
                mock_ticker = MagicMock()
                mock_ticker.history.return_value = pd.DataFrame({"Close": hist})
                mock_yf.return_value = mock_ticker

                result = svc._fetch_finnhub(scores)

        assert result is not None
        assert -1.0 <= result <= 1.0
        assert "Finnhub" not in scores.errors  # RSI succeeded, no error shown

    def test_no_finnhub_key_uses_rsi_fallback(self) -> None:
        svc = _make_service(key="")
        scores = SentimentScores()
        hist = _spy_history(60)

        with patch("yfinance.Ticker") as mock_yf:
            mock_ticker = MagicMock()
            mock_ticker.history.return_value = pd.DataFrame({"Close": hist})
            mock_yf.return_value = mock_ticker

            result = svc._fetch_finnhub(scores)

        assert result is not None
        assert -1.0 <= result <= 1.0

    def test_both_finnhub_and_rsi_fail_returns_none(self) -> None:
        from urllib.error import HTTPError

        svc = _make_service(key="testkey")
        scores = SentimentScores()

        with patch.object(svc, "_get_json", side_effect=HTTPError(None, 403, "Forbidden", {}, None)):
            with patch("yfinance.Ticker") as mock_yf:
                mock_ticker = MagicMock()
                mock_ticker.history.return_value = pd.DataFrame({"Close": pd.Series([], dtype=float)})
                mock_yf.return_value = mock_ticker

                result = svc._fetch_finnhub(scores)

        assert result is None
        assert "Finnhub" in scores.errors


# ── Normalization helpers ──────────────────────────────────────────────────

class TestNormalization:
    def test_normalize_0_100_bounds(self) -> None:
        svc = _make_service()
        assert svc._normalize_0_100(0.0) == -1.0
        assert svc._normalize_0_100(50.0) == 0.0
        assert svc._normalize_0_100(100.0) == 1.0

    def test_normalize_0_100_clamps(self) -> None:
        svc = _make_service()
        assert svc._normalize_0_100(-10.0) == -1.0
        assert svc._normalize_0_100(110.0) == 1.0

    def test_normalize_put_call_bullish_threshold(self) -> None:
        svc = _make_service()
        assert svc._normalize_put_call(0.60) == 1.0
        assert svc._normalize_put_call(0.70) == 1.0

    def test_normalize_put_call_bearish_threshold(self) -> None:
        svc = _make_service()
        assert svc._normalize_put_call(1.25) == -1.0
        assert svc._normalize_put_call(1.50) == -1.0

    def test_normalize_put_call_midpoint(self) -> None:
        svc = _make_service()
        mid = (0.70 + 1.25) / 2
        result = svc._normalize_put_call(mid)
        assert pytest.approx(result, abs=0.01) == 0.0
