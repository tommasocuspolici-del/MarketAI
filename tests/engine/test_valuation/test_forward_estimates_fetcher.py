"""Tests per ForwardEstimatesFetcher — Valuation Engine Blocco 3."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from engine.analytics.valuation.forward_estimates_fetcher import (
    ForwardEstimatesFetcher,
    ForwardEstimate,
)


@pytest.fixture()
def mock_client():
    client = MagicMock()
    client.query.return_value = []
    return client


@pytest.fixture()
def fetcher(mock_client):
    return ForwardEstimatesFetcher(client=mock_client)


class TestForwardEstimateShape:
    def test_returns_forward_estimate_instance(self, fetcher):
        result = fetcher.get_forward_estimate("^GSPC", date(2024, 1, 1))
        assert isinstance(result, ForwardEstimate)

    def test_ticker_propagated(self, fetcher):
        result = fetcher.get_forward_estimate("AAPL", date(2024, 1, 1))
        assert result.ticker == "AAPL"

    def test_is_always_estimated(self, fetcher):
        result = fetcher.get_forward_estimate("^GSPC", date(2024, 1, 1))
        assert result.is_estimated is True

    def test_source_none_when_no_data(self, fetcher):
        with patch("yfinance.Ticker") as mock_yf:
            mock_yf.return_value.info = {}
            result = fetcher.get_forward_estimate("UNKNOWN", date(2024, 1, 1))
        assert result.source == "none"
        assert result.forward_pe is None


class TestAlphaVantageSource:
    def test_reads_pe_forward_from_av(self, mock_client):
        """Usa pe_forward da fundamentals_valuation se disponibile."""
        mock_client.query.return_value = [(18.5, 22.0)]
        f = ForwardEstimatesFetcher(client=mock_client)
        result = f.get_forward_estimate("AAPL", date(2024, 1, 1))
        assert result.forward_pe == pytest.approx(18.5)
        assert result.source == "av"

    def test_skips_av_when_none_returned(self, mock_client):
        """Fallback a yfinance se pe_forward è NULL in DB."""
        mock_client.query.return_value = [(None, 22.0)]
        with patch("yfinance.Ticker") as mock_yf:
            mock_yf.return_value.info = {"forwardPE": 19.0, "currentPrice": 100.0}
            f = ForwardEstimatesFetcher(client=mock_client)
            result = f.get_forward_estimate("AAPL", date(2024, 1, 1))
        assert result.source == "yfinance"


class TestYfinanceSource:
    def test_uses_yfinance_forward_pe(self, mock_client):
        mock_client.query.return_value = []
        with patch("yfinance.Ticker") as mock_yf:
            mock_yf.return_value.info = {"forwardPE": 21.5, "currentPrice": 450.0}
            f = ForwardEstimatesFetcher(client=mock_client)
            result = f.get_forward_estimate("SPY", date(2024, 1, 1))
        assert result.forward_pe == pytest.approx(21.5)
        assert result.source == "yfinance"

    def test_eps_forward_derived_from_price(self, mock_client):
        """eps_forward = price / forwardPE se price disponibile."""
        mock_client.query.return_value = []
        with patch("yfinance.Ticker") as mock_yf:
            mock_yf.return_value.info = {"forwardPE": 20.0, "currentPrice": 400.0}
            f = ForwardEstimatesFetcher(client=mock_client)
            result = f.get_forward_estimate("SPY", date(2024, 1, 1))
        assert result.eps_forward == pytest.approx(20.0)  # 400 / 20 = 20

    def test_eps_forward_none_without_price(self, mock_client):
        mock_client.query.return_value = []
        with patch("yfinance.Ticker") as mock_yf:
            mock_yf.return_value.info = {"forwardPE": 20.0}
            f = ForwardEstimatesFetcher(client=mock_client)
            result = f.get_forward_estimate("SPY", date(2024, 1, 1))
        assert result.eps_forward is None

    def test_ignores_zero_forward_pe(self, mock_client):
        """forwardPE=0 non è valido — deve cadere in fallback."""
        mock_client.query.return_value = []
        with patch("yfinance.Ticker") as mock_yf:
            mock_yf.return_value.info = {"forwardPE": 0.0}
            f = ForwardEstimatesFetcher(client=mock_client)
            result = f.get_forward_estimate("SPY", date(2024, 1, 1))
        assert result.source in ("yaml_manual", "none")

    def test_yfinance_exception_falls_back(self, mock_client):
        mock_client.query.return_value = []
        with patch("yfinance.Ticker", side_effect=Exception("network error")):
            f = ForwardEstimatesFetcher(client=mock_client)
            result = f.get_forward_estimate("SPY", date(2024, 1, 1))
        assert result.source in ("yaml_manual", "none")


class TestYamlManualSource:
    def test_yaml_manual_used_as_last_resort(self, mock_client):
        """YAML manuale attivato solo se tutte le altre fonti falliscono."""
        mock_client.query.return_value = []
        f = ForwardEstimatesFetcher(client=mock_client)
        # Inietta manualmente yaml con una entry
        f._yaml_manual = {"TEST_TICKER": {"forward_pe": 15.0, "eps_forward": 8.5}}
        with patch("yfinance.Ticker") as mock_yf:
            mock_yf.return_value.info = {}
            result = f.get_forward_estimate("TEST_TICKER", date(2024, 1, 1))
        assert result.forward_pe == pytest.approx(15.0)
        assert result.eps_forward == pytest.approx(8.5)
        assert result.source == "yaml_manual"

    def test_yaml_manual_without_eps_forward(self, mock_client):
        mock_client.query.return_value = []
        f = ForwardEstimatesFetcher(client=mock_client)
        f._yaml_manual = {"TEST2": {"forward_pe": 18.0}}
        with patch("yfinance.Ticker") as mock_yf:
            mock_yf.return_value.info = {}
            result = f.get_forward_estimate("TEST2", date(2024, 1, 1))
        assert result.forward_pe == pytest.approx(18.0)
        assert result.eps_forward is None


class TestPersistEstimate:
    def test_persist_returns_true_on_success(self, mock_client):
        f = ForwardEstimatesFetcher(client=mock_client)
        est = ForwardEstimate(ticker="SPY", as_of=date(2024, 1, 1),
                              forward_pe=20.0, eps_forward=None,
                              source="yfinance")
        assert f.persist_estimate(est) is True

    def test_persist_returns_false_when_no_pe(self, mock_client):
        f = ForwardEstimatesFetcher(client=mock_client)
        est = ForwardEstimate(ticker="SPY", as_of=date(2024, 1, 1),
                              forward_pe=None, eps_forward=None,
                              source="none")
        assert f.persist_estimate(est) is False

    def test_persist_calls_client_execute(self, mock_client):
        f = ForwardEstimatesFetcher(client=mock_client)
        est = ForwardEstimate(ticker="SPY", as_of=date(2024, 1, 1),
                              forward_pe=19.5, eps_forward=None,
                              source="yfinance")
        f.persist_estimate(est)
        mock_client.execute.assert_called_once()
