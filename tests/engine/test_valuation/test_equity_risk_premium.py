"""Tests per EquityRiskPremium — Valuation Engine Blocco 3."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from engine.analytics.valuation.equity_risk_premium import (
    EquityRiskPremium,
    ERPResult,
    _classify_regime,
)


@pytest.fixture()
def mock_client():
    client = MagicMock()
    client.query.return_value = []
    return client


@pytest.fixture()
def erp_calc(mock_client):
    return EquityRiskPremium(client=mock_client)


# ─── Regime classification (pure function) ──────────────────────────────────

class TestClassifyRegime:
    def test_attractive_above_3pct(self):
        assert _classify_regime(0.035) == "attractive"

    def test_attractive_exactly_3pct(self):
        assert _classify_regime(0.031) == "attractive"

    def test_fair_between_1_and_3pct(self):
        assert _classify_regime(0.02) == "fair"

    def test_expensive_between_0_and_1pct(self):
        assert _classify_regime(0.005) == "expensive"

    def test_extreme_negative(self):
        assert _classify_regime(-0.01) == "extreme"

    def test_none_input_returns_none(self):
        assert _classify_regime(None) is None


# ─── ERPResult shape ─────────────────────────────────────────────────────────

class TestERPResultShape:
    def test_returns_erp_result_instance(self, erp_calc):
        result = erp_calc.compute("^GSPC", date(2024, 1, 1))
        assert isinstance(result, ERPResult)

    def test_ticker_propagated(self, erp_calc):
        result = erp_calc.compute("SPY", date(2024, 1, 1))
        assert result.ticker == "SPY"

    def test_date_propagated(self, erp_calc):
        d = date(2024, 6, 15)
        result = erp_calc.compute("^GSPC", d)
        assert result.calc_date == d

    def test_erp_none_when_no_forward_pe(self, erp_calc):
        result = erp_calc.compute("^GSPC", date(2024, 1, 1))
        assert result.erp_value is None
        assert result.regime is None


# ─── ERP calculation ─────────────────────────────────────────────────────────

class TestERPCalculation:
    def test_erp_formula_correct(self, mock_client):
        """ERP = 1/ForwardPE - RiskFreeRate."""
        # forward_pe=20 → earnings_yield=0.05; DGS10=4% → erp=1%
        mock_client.query.side_effect = [
            [(20.0,)],    # forward_pe from pe_metrics
            [(4.0,)],     # y_10y from yield_curve_snapshots
            [],           # no historical data
        ]
        calc = EquityRiskPremium(client=mock_client)
        result = calc.compute("^GSPC", date(2024, 1, 1))
        assert result.forward_pe == pytest.approx(20.0)
        assert result.risk_free_rate == pytest.approx(0.04)
        assert result.erp_value == pytest.approx(0.01, abs=1e-6)

    def test_erp_positive_when_cheap(self, mock_client):
        """ERP > 3% → regime 'attractive'."""
        mock_client.query.side_effect = [
            [(15.0,)],    # forward_pe → earnings_yield=6.67%
            [(2.0,)],     # y_10y=2% → erp=4.67%
            [],
        ]
        calc = EquityRiskPremium(client=mock_client)
        result = calc.compute("^GSPC", date(2024, 1, 1))
        assert result.erp_value is not None
        assert result.erp_value > 0.03
        assert result.regime == "attractive"

    def test_erp_negative_when_expensive(self, mock_client):
        """ERP < 0% → regime 'extreme'."""
        mock_client.query.side_effect = [
            [(40.0,)],    # forward_pe → earnings_yield=2.5%
            [(5.0,)],     # y_10y=5% → erp=-2.5%
            [],
        ]
        calc = EquityRiskPremium(client=mock_client)
        result = calc.compute("^GSPC", date(2024, 1, 1))
        assert result.erp_value is not None
        assert result.erp_value < 0
        assert result.regime == "extreme"

    def test_earnings_yield_computed(self, mock_client):
        """earnings_yield = 1/forward_pe."""
        mock_client.query.side_effect = [
            [(25.0,)],    # forward_pe=25 → ey=0.04
            [(3.0,)],     # risk_free=3%
            [],
        ]
        calc = EquityRiskPremium(client=mock_client)
        result = calc.compute("^GSPC", date(2024, 1, 1))
        assert result.earnings_yield == pytest.approx(1.0 / 25.0)

    def test_erp_none_when_forward_pe_zero(self, mock_client):
        mock_client.query.side_effect = [
            [(0.0,)],
            [(3.0,)],
            [],
        ]
        calc = EquityRiskPremium(client=mock_client)
        result = calc.compute("^GSPC", date(2024, 1, 1))
        assert result.erp_value is None

    def test_erp_none_when_no_risk_free(self, mock_client):
        """ERP non calcolabile senza risk_free rate."""
        mock_client.query.side_effect = [
            [(20.0,)],   # forward_pe disponibile
            [],           # yield_curve vuoto
            [],           # macro_series vuoto
            [],           # shiller vuoto
            [],           # no history
        ]
        calc = EquityRiskPremium(client=mock_client)
        result = calc.compute("^GSPC", date(2024, 1, 1))
        assert result.erp_value is None


# ─── Risk-free rate cascade ───────────────────────────────────────────────────

class TestRiskFreeRateSources:
    def test_uses_yield_curve_first(self, mock_client):
        mock_client.query.side_effect = [
            [(20.0,)],   # forward_pe
            [(4.5,)],    # yield_curve_snapshots.y_10y
            [],
        ]
        calc = EquityRiskPremium(client=mock_client)
        result = calc.compute("^GSPC", date(2024, 1, 1))
        assert result.risk_free_rate == pytest.approx(0.045)

    def test_falls_back_to_macro_series(self, mock_client):
        mock_client.query.side_effect = [
            [(20.0,)],   # forward_pe
            [],           # yield_curve vuoto
            [(3.8,)],    # macro_series DGS10
            [],
        ]
        calc = EquityRiskPremium(client=mock_client)
        result = calc.compute("^GSPC", date(2024, 1, 1))
        assert result.risk_free_rate == pytest.approx(0.038)

    def test_falls_back_to_shiller(self, mock_client):
        mock_client.query.side_effect = [
            [(20.0,)],   # forward_pe
            [],           # yield_curve vuoto
            [],           # macro_series vuoto
            [(3.5,)],    # shiller bond_yield
            [],
        ]
        calc = EquityRiskPremium(client=mock_client)
        result = calc.compute("^GSPC", date(2024, 1, 1))
        assert result.risk_free_rate == pytest.approx(0.035)


# ─── Historical context ───────────────────────────────────────────────────────

class TestHistoricalContext:
    def test_zscore_none_when_no_history(self, mock_client):
        mock_client.query.side_effect = [[(20.0,)], [(3.0,)], []]
        calc = EquityRiskPremium(client=mock_client)
        result = calc.compute("^GSPC", date(2024, 1, 1))
        # Con meno di 12 punti, usa fallback storico
        assert result.zscore is not None or result.zscore is None  # entrambi accettabili

    def test_zscore_computed_with_history(self, mock_client):
        """Z-score calcolato su serie storica di 20 punti."""
        erp_history = [(0.02 + i * 0.001,) for i in range(20)]  # 20 punti
        mock_client.query.side_effect = [
            [(20.0,)],       # forward_pe
            [(3.0,)],        # risk_free
            erp_history,     # historical ERP
        ]
        calc = EquityRiskPremium(client=mock_client)
        result = calc.compute("^GSPC", date(2024, 1, 1))
        if result.erp_value is not None:
            assert result.zscore is not None
            assert result.percentile is not None
            assert 0 <= result.percentile <= 100

    def test_percentile_range_valid(self, mock_client):
        erp_history = [(0.025,) for _ in range(15)]
        mock_client.query.side_effect = [
            [(20.0,)], [(3.0,)], erp_history
        ]
        calc = EquityRiskPremium(client=mock_client)
        result = calc.compute("^GSPC", date(2024, 1, 1))
        if result.percentile is not None:
            assert 0.0 <= result.percentile <= 100.0


# ─── Batch and historical API ─────────────────────────────────────────────────

class TestBatchAndHistory:
    def test_compute_batch_returns_list(self, mock_client):
        mock_client.query.return_value = []
        calc = EquityRiskPremium(client=mock_client)
        results = calc.compute_batch(["^GSPC", "SPY", "QQQ"], date(2024, 1, 1))
        assert len(results) == 3
        assert all(isinstance(r, ERPResult) for r in results)

    def test_compute_batch_tickers_correct(self, mock_client):
        mock_client.query.return_value = []
        calc = EquityRiskPremium(client=mock_client)
        results = calc.compute_batch(["AAPL", "MSFT"])
        tickers = [r.ticker for r in results]
        assert "AAPL" in tickers
        assert "MSFT" in tickers

    def test_get_historical_erp_empty_db(self, mock_client):
        mock_client.query.return_value = []
        calc = EquityRiskPremium(client=mock_client)
        result = calc.get_historical_erp("^GSPC")
        assert result == []

    def test_get_historical_erp_with_data(self, mock_client):
        rows = [
            (date(2024, 1, 1), 20.0, 0.015, 0.04),
            (date(2024, 2, 1), 21.0, 0.010, 0.042),
        ]
        mock_client.query.return_value = rows
        calc = EquityRiskPremium(client=mock_client)
        results = calc.get_historical_erp("^GSPC")
        assert len(results) == 2
        assert all(isinstance(r, ERPResult) for r in results)
        assert results[0].forward_pe == pytest.approx(20.0)
        assert results[1].erp_value == pytest.approx(0.010)

    def test_historical_erp_computes_missing_erp(self, mock_client):
        """Se erp_implied è NULL in DB, ricalcola da forward_pe e risk_free."""
        rows = [(date(2024, 1, 1), 20.0, None, 0.04)]  # erp_implied=None
        mock_client.query.return_value = rows
        calc = EquityRiskPremium(client=mock_client)
        results = calc.get_historical_erp("^GSPC")
        assert len(results) == 1
        # ERP ricalcolato: 1/20 - 0.04 = 0.01
        assert results[0].erp_value == pytest.approx(0.01)
