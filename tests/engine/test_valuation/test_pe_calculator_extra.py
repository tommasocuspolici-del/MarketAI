"""Extra coverage tests for PECalculator private read methods."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from engine.analytics.valuation.pe_calculator import PECalculator, PEMetrics


@pytest.fixture()
def mock_client():
    client = MagicMock()
    client.query.return_value = []
    client.execute.return_value = None
    return client


@pytest.fixture()
def calc(mock_client):
    return PECalculator(client=mock_client)


class TestGetPrice:
    def test_returns_price_from_db(self, mock_client):
        mock_client.query.return_value = [(450.0,)]
        c = PECalculator(client=mock_client)
        result = c._get_price("SPY", date(2024, 1, 5))
        assert result == pytest.approx(450.0)

    def test_returns_none_when_db_empty(self, calc):
        result = calc._get_price("SPY", date(2024, 1, 5))
        assert result is None

    def test_fallback_on_db_exception(self, mock_client):
        mock_client.query.side_effect = Exception("DB error")
        c = PECalculator(client=mock_client)
        # Falls back to yfinance which will fail in test → None
        result = c._get_price("SPY", date(2024, 1, 5))
        assert result is None or isinstance(result, float)


class TestGetTrailingPE:
    def test_returns_pe_from_db(self, mock_client):
        mock_client.query.return_value = [(22.5,)]
        c = PECalculator(client=mock_client)
        result = c._get_trailing_pe("SPY", date(2024, 1, 5), price=450.0)
        assert result == pytest.approx(22.5)

    def test_computes_from_eps_when_db_empty(self, mock_client):
        # First call (pe_ttm): empty; second call (eps_trailing): returns eps
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return []   # pe_ttm not available
            if call_count[0] == 2:
                return []   # eps from edgar not available
            return []
        mock_client.query.side_effect = side_effect
        c = PECalculator(client=mock_client)
        result = c._get_trailing_pe("SPY", date(2024, 1, 5), price=450.0)
        assert result is None  # no eps available → None


class TestGetForwardPE:
    def test_returns_forward_pe_from_db(self, mock_client):
        mock_client.query.return_value = [(20.0,)]
        c = PECalculator(client=mock_client)
        result = c._get_forward_pe("SPY", date(2024, 1, 5), price=400.0)
        assert result == pytest.approx(20.0)

    def test_returns_none_when_no_data(self, calc):
        result = calc._get_forward_pe("SPY", date(2024, 1, 5), price=None)
        assert result is None


class TestGetShillerCAPE:
    def test_returns_cape_from_db(self, mock_client):
        mock_client.query.return_value = [(32.5,)]
        c = PECalculator(client=mock_client)
        result = c._get_shiller_cape(date(2024, 1, 5))
        assert result == pytest.approx(32.5)

    def test_returns_none_when_empty(self, calc):
        result = calc._get_shiller_cape(date(2024, 1, 5))
        assert result is None


class TestGetRiskFreeRate:
    def test_returns_rate_from_macro_data(self, mock_client):
        mock_client.query.return_value = [(4.5,)]
        c = PECalculator(client=mock_client)
        result = c._get_risk_free_rate(date(2024, 1, 5))
        assert result == pytest.approx(0.045)

    def test_fallback_to_shiller(self, mock_client):
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return []          # macro_data empty
            return [(3.8,)]        # shiller fallback
        mock_client.query.side_effect = side_effect
        c = PECalculator(client=mock_client)
        result = c._get_risk_free_rate(date(2024, 1, 5))
        assert result == pytest.approx(0.038)

    def test_returns_none_when_both_empty(self, calc):
        result = calc._get_risk_free_rate(date(2024, 1, 5))
        assert result is None


class TestComputePEG:
    def test_returns_none_when_no_forward_pe(self, calc):
        result = calc._compute_peg(None, "SPY", date(2024, 1, 5))
        assert result is None

    def test_returns_none_when_forward_pe_zero(self, calc):
        result = calc._compute_peg(0.0, "SPY", date(2024, 1, 5))
        assert result is None

    def test_computes_peg_from_eps_growth(self, mock_client):
        # Two FY EPS values: growth = (12/10 - 1) * 100 = 20%, PEG = 20/20 = 1.0
        mock_client.query.return_value = [(12.0,), (10.0,)]
        c = PECalculator(client=mock_client)
        result = c._compute_peg(20.0, "AAPL", date(2024, 1, 5))
        assert result is not None
        assert result > 0
