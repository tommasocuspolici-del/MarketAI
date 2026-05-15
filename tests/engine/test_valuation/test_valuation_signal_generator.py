"""Tests per ValuationSignalGenerator — integrazione PE + context → segnale."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from engine.analytics.valuation.schemas import PEMetrics, ValuationSignalResult
from engine.analytics.valuation.valuation_signal_generator import ValuationSignalGenerator


def _make_mock_client():
    client = MagicMock()
    client.query.return_value = []
    client.execute.return_value = None
    return client


@pytest.fixture()
def mock_client():
    return _make_mock_client()


@pytest.fixture()
def generator(mock_client):
    return ValuationSignalGenerator(client=mock_client)


def _make_pe_metrics(**kwargs) -> PEMetrics:
    defaults = dict(
        metric_date=date(2024, 1, 1),
        ticker="^GSPC",
        price=4500.0,
        trailing_pe=20.0,
        forward_pe=18.0,
        shiller_cape=30.0,
        peg_ratio=None,
        erp_implied=0.025,
        erp_regime="fair",
        eps_trailing_4q=225.0,
        eps_forward_1y=250.0,
        risk_free_rate=0.045,
    )
    defaults.update(kwargs)
    return PEMetrics(**defaults)


class TestValuationSignalGeneratorOutput:
    def test_compute_returns_signal_result(self, generator):
        with (
            patch.object(generator._calc, "compute", return_value=_make_pe_metrics()),
            patch.object(generator._ctx, "build", return_value={
                "composite_score": 0.1,
                "label": "fair_value",
                "trailing_zscore": 0.3,
                "forward_zscore": 0.2,
                "cape_zscore": 0.5,
            }),
        ):
            result = generator.compute("^GSPC", date(2024, 1, 1))
        assert isinstance(result, ValuationSignalResult)

    def test_score_in_valid_range(self, generator):
        with (
            patch.object(generator._calc, "compute", return_value=_make_pe_metrics()),
            patch.object(generator._ctx, "build", return_value={
                "composite_score": 0.3, "label": "cheap",
                "trailing_zscore": -1.0, "forward_zscore": -0.8, "cape_zscore": -0.5,
            }),
        ):
            result = generator.compute()
        assert -1.0 <= result.valuation_score <= 1.0

    def test_signal_date_propagated(self, generator):
        d = date(2024, 6, 15)
        with (
            patch.object(generator._calc, "compute", return_value=_make_pe_metrics(metric_date=d)),
            patch.object(generator._ctx, "build", return_value={
                "composite_score": 0.0, "label": "fair_value",
            }),
        ):
            result = generator.compute("^GSPC", d)
        assert result.signal_date == d

    def test_ticker_propagated(self, generator):
        with (
            patch.object(generator._calc, "compute", return_value=_make_pe_metrics()),
            patch.object(generator._ctx, "build", return_value={
                "composite_score": 0.0, "label": "fair_value",
            }),
        ):
            result = generator.compute("SPY")
        assert result.ticker == "SPY"

    def test_persist_called_on_success(self, generator):
        with (
            patch.object(generator._calc, "compute", return_value=_make_pe_metrics()),
            patch.object(generator._ctx, "build", return_value={
                "composite_score": 0.1, "label": "fair_value",
            }),
            patch.object(generator, "_persist") as mock_persist,
        ):
            generator.compute()
        mock_persist.assert_called_once()

    def test_high_pe_gives_negative_signal(self, generator):
        with (
            patch.object(generator._calc, "compute", return_value=_make_pe_metrics(
                erp_implied=-0.01,  # earnings yield < risk free → expensive
            )),
            patch.object(generator._ctx, "build", return_value={
                "composite_score": -0.7,
                "label": "stretched",
                "trailing_zscore": 2.0,
                "forward_zscore": 1.8,
                "cape_zscore": 2.5,
            }),
        ):
            result = generator.compute()
        assert result.valuation_score <= 0.0

    def test_low_pe_gives_positive_signal(self, generator):
        with (
            patch.object(generator._calc, "compute", return_value=_make_pe_metrics(
                erp_implied=0.06,
            )),
            patch.object(generator._ctx, "build", return_value={
                "composite_score": 0.6,
                "label": "cheap",
                "trailing_zscore": -1.5,
                "forward_zscore": -1.2,
                "cape_zscore": -1.0,
            }),
        ):
            result = generator.compute()
        assert result.valuation_score >= 0.0


class TestValuationSignalGetLatest:
    def test_get_latest_returns_float_when_available(self, mock_client):
        mock_client.query.return_value = [(0.35,)]
        gen = ValuationSignalGenerator(client=mock_client)
        result = gen.get_latest_signal()
        assert result == pytest.approx(0.35)

    def test_get_latest_returns_none_when_empty(self, mock_client):
        mock_client.query.return_value = []
        gen = ValuationSignalGenerator(client=mock_client)
        assert gen.get_latest_signal() is None

    def test_get_latest_handles_db_error(self, mock_client):
        mock_client.query.side_effect = RuntimeError("DB error")
        gen = ValuationSignalGenerator(client=mock_client)
        assert gen.get_latest_signal() is None
