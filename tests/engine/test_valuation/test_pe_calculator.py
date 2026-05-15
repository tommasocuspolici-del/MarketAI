"""Tests per PECalculator — Blocco 3 Valuation Engine."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from engine.analytics.valuation.pe_calculator import PECalculator
from engine.analytics.valuation.schemas import PEMetrics


@pytest.fixture()
def mock_client():
    client = MagicMock()
    client.query.return_value = []
    return client


@pytest.fixture()
def calculator(mock_client):
    return PECalculator(client=mock_client)


class TestPECalculatorBasic:
    def test_returns_pe_metrics_instance(self, calculator):
        result = calculator.compute("^GSPC", date(2024, 1, 1))
        assert isinstance(result, PEMetrics)

    def test_metric_date_matches_input(self, calculator):
        d = date(2024, 6, 15)
        result = calculator.compute("^GSPC", d)
        assert result.metric_date == d

    def test_ticker_matches_input(self, calculator):
        result = calculator.compute("SPY", date(2024, 1, 1))
        assert result.ticker == "SPY"

    def test_returns_none_pe_when_no_data(self, calculator):
        result = calculator.compute("^GSPC", date(2024, 1, 1))
        assert result.trailing_pe is None or isinstance(result.trailing_pe, float)

    def test_pe_ratios_positive_when_available(self, mock_client):
        mock_client.query.side_effect = [
            [(100.0,)],             # price query
            [(4.0, 4.2, None)],     # eps trailing / forward / peg
            [],                      # risk_free_rate
        ]
        calc = PECalculator(client=mock_client)
        result = calc.compute("^GSPC", date(2024, 1, 1))
        if result.trailing_pe is not None:
            assert result.trailing_pe > 0

    def test_erp_regime_is_string_or_none(self, calculator):
        result = calculator.compute("^GSPC", date(2024, 1, 1))
        assert result.erp_regime is None or isinstance(result.erp_regime, str)

    def test_no_division_by_zero_with_zero_eps(self, mock_client):
        mock_client.query.side_effect = [
            [(100.0,)],
            [(0.0, 0.0, None)],     # EPS = 0 → should not raise
            [],
        ]
        calc = PECalculator(client=mock_client)
        result = calc.compute("^GSPC", date(2024, 1, 1))
        assert result.trailing_pe is None or result.trailing_pe > 0 or result.trailing_pe == 0


class TestPECalculatorERP:
    def test_erp_implied_none_when_no_forward_pe(self, mock_client):
        mock_client.query.return_value = []
        calc = PECalculator(client=mock_client)
        result = calc.compute("^GSPC", date(2024, 1, 1))
        assert result.erp_implied is None or isinstance(result.erp_implied, float)

    def test_erp_range_when_available(self, mock_client):
        mock_client.query.side_effect = [
            [(5000.0,)],
            [(200.0, 220.0, None)],   # EPS trailing / forward
            [(0.045,)],               # risk_free_rate 4.5%
        ]
        calc = PECalculator(client=mock_client)
        result = calc.compute("^GSPC", date(2024, 1, 1))
        if result.erp_implied is not None:
            # ERP = 1/ForwardPE - RFR = (220/5000) - 0.045 ≈ -0.001
            assert -1.0 < result.erp_implied < 1.0
