"""Tests per CorrelationSignalGenerator."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from engine.analytics.correlation.correlation_signal_generator import (
    CorrelationSignalGenerator,
    CorrelationSignalResult,
)


@pytest.fixture()
def mock_client():
    client = MagicMock()
    client.query.return_value = []
    return client


@pytest.fixture()
def gen(mock_client):
    return CorrelationSignalGenerator(client=mock_client)


# ─── CorrelationSignalResult shape ───────────────────────────────────────────

class TestResultShape:
    def test_returns_result_instance(self, gen):
        result = gen.compute_from_db(date(2024, 1, 1))
        assert isinstance(result, CorrelationSignalResult)

    def test_signal_in_range_empty_db(self, gen):
        result = gen.compute_from_db(date(2024, 1, 1))
        assert -1.0 <= result.correlation_signal <= 1.0

    def test_confidence_in_range(self, gen):
        result = gen.compute_from_db(date(2024, 1, 1))
        assert 0.0 <= result.confidence <= 1.0

    def test_lead_lag_count_zero_empty(self, gen):
        result = gen.compute_from_db(date(2024, 1, 1))
        assert result.lead_lag_count == 0

    def test_signal_date_propagated(self, gen):
        d = date(2024, 6, 15)
        result = gen.compute_from_db(d)
        assert result.signal_date == d


# ─── Signal computation ───────────────────────────────────────────────────────

class TestSignalComputation:
    def test_uses_cross_asset_signal(self, mock_client):
        """correlation_signal primario viene da cross_asset_regime."""
        today = date.today()
        mock_client.query.side_effect = [
            [(0.40, 0.70, "normal", 0.20, 0.05, 0.55, today)],  # cross_asset_regime
            [],  # lead_lag_signals
        ]
        g = CorrelationSignalGenerator(client=mock_client)
        result = g.compute_from_db(today)
        # Senza lead-lag, usa solo cross_asset_signal
        assert result.correlation_signal == pytest.approx(0.40, abs=0.01)

    def test_blends_lead_lag(self, mock_client):
        """Con lead-lag disponibile, blenda 85/15."""
        today = date.today()
        mock_client.query.side_effect = [
            [(0.40, 0.70, "normal", 0.20, 0.05, 0.55, today)],
            [("bullish_lead", 0.50, 0.02),
             ("bullish_lead", 0.40, 0.03)],
        ]
        g = CorrelationSignalGenerator(client=mock_client)
        result = g.compute_from_db(today)
        # combined = 0.85*0.40 + 0.15*(lead_lag_net)
        assert result.correlation_signal > 0
        assert result.lead_lag_component is not None

    def test_bearish_lead_lag_reduces_signal(self, mock_client):
        """Lead-lag negativo abbassa il segnale finale."""
        today = date.today()
        mock_client.query.side_effect = [
            [(0.30, 0.60, "normal", 0.15, 0.05, 0.40, today)],
            [("bearish_lead", 0.50, 0.02),
             ("bearish_lead", 0.45, 0.03)],
        ]
        g = CorrelationSignalGenerator(client=mock_client)
        result = g.compute_from_db(today)
        assert result.correlation_signal < 0.30  # abbassato dal bearish lead-lag

    def test_neutral_lead_lag_not_included(self, mock_client):
        """Lead 'neutral' non contribuisce al segnale."""
        today = date.today()
        mock_client.query.side_effect = [
            [(0.20, 0.55, "normal", 0.10, -0.05, 0.30, today)],
            [("neutral", 0.50, 0.02)],
        ]
        g = CorrelationSignalGenerator(client=mock_client)
        result = g.compute_from_db(today)
        # neutral skippato → lead_lag_component è None (nessun valore signal_val)
        assert result.lead_lag_component is None or result.lead_lag_component == 0

    def test_signal_clipped_to_range(self, mock_client):
        """Segnale sempre in [-1, +1]."""
        today = date.today()
        mock_client.query.side_effect = [
            [(2.0, 0.99, "normal", 0.9, 0.8, 0.95, today)],  # cross > 1
            [],
        ]
        g = CorrelationSignalGenerator(client=mock_client)
        result = g.compute_from_db(today)
        assert -1.0 <= result.correlation_signal <= 1.0


# ─── Freshness and confidence ─────────────────────────────────────────────────

class TestFreshnessConfidence:
    def test_high_confidence_fresh_data(self, mock_client):
        """Dati di oggi → alta confidenza."""
        today = date.today()
        mock_client.query.side_effect = [
            [(0.30, 0.65, "normal", 0.20, 0.05, 0.45, today)],
            [],
        ]
        g = CorrelationSignalGenerator(client=mock_client)
        result = g.compute_from_db(today)
        assert result.confidence > 0.5
        assert result.data_freshness_days == 0

    def test_low_confidence_stale_data(self, mock_client):
        """Dati vecchi di 10gg → bassa confidenza."""
        today = date.today()
        old_date = today - timedelta(days=10)
        mock_client.query.side_effect = [
            [(0.30, 0.65, "normal", 0.20, 0.05, 0.45, old_date)],
            [],
        ]
        g = CorrelationSignalGenerator(client=mock_client)
        result = g.compute_from_db(today)
        assert result.confidence < 0.5
        assert result.data_freshness_days == 10

    def test_zero_confidence_no_data(self, mock_client):
        """Nessun dato → confidenza zero."""
        mock_client.query.return_value = []
        g = CorrelationSignalGenerator(client=mock_client)
        result = g.compute_from_db(date(2024, 1, 1))
        assert result.confidence == 0.0

    def test_lead_lag_bonus_increases_confidence(self, mock_client):
        """5+ lead-lag significativi aumentano la confidenza."""
        today = date.today()
        ll_rows = [("bullish_lead", 0.4, 0.02)] * 5
        mock_client.query.side_effect = [
            [(0.30, 0.65, "normal", 0.20, 0.05, 0.45, today)],
            ll_rows,
        ]
        g = CorrelationSignalGenerator(client=mock_client)
        result = g.compute_from_db(today)
        assert result.lead_lag_count == 5
        assert result.confidence > 0.6  # bonus lead-lag attivo


# ─── get_latest_signal ────────────────────────────────────────────────────────

class TestGetLatestSignal:
    def test_returns_float_when_fresh(self, mock_client):
        today = date.today()
        mock_client.query.return_value = [(0.25, today)]
        g = CorrelationSignalGenerator(client=mock_client)
        result = g.get_latest_signal()
        assert result == pytest.approx(0.25)

    def test_returns_none_empty_db(self, mock_client):
        mock_client.query.return_value = []
        g = CorrelationSignalGenerator(client=mock_client)
        assert g.get_latest_signal() is None

    def test_returns_none_stale(self, mock_client):
        old = date.today() - timedelta(days=10)
        mock_client.query.return_value = [(0.30, old)]
        g = CorrelationSignalGenerator(client=mock_client)
        assert g.get_latest_signal() is None

    def test_clips_to_range(self, mock_client):
        today = date.today()
        mock_client.query.return_value = [(1.5, today)]  # fuori range
        g = CorrelationSignalGenerator(client=mock_client)
        result = g.get_latest_signal()
        assert result is not None
        assert -1.0 <= result <= 1.0

    def test_returns_none_on_db_error(self, mock_client):
        mock_client.query.side_effect = Exception("db error")
        g = CorrelationSignalGenerator(client=mock_client)
        assert g.get_latest_signal() is None


# ─── Lead-lag aggregation ─────────────────────────────────────────────────────

class TestLeadLagAggregation:
    def test_net_bullish_positive_signal(self, mock_client):
        """Net bullish lead-lag → segnale positivo."""
        today = date.today()
        mock_client.query.side_effect = [
            [(0.0, 0.5, "normal", None, None, None, today)],
            [("bullish_lead", 0.5, 0.01),
             ("bullish_lead", 0.4, 0.02)],
        ]
        g = CorrelationSignalGenerator(client=mock_client)
        result = g.compute_from_db(today)
        assert result.lead_lag_component is not None
        assert result.lead_lag_component > 0

    def test_mixed_signals_balanced(self, mock_client):
        """Segnali bullish e bearish bilanciati → near zero."""
        today = date.today()
        mock_client.query.side_effect = [
            [(0.0, 0.5, "normal", None, None, None, today)],
            [("bullish_lead", 0.5, 0.01),
             ("bearish_lead", 0.5, 0.01)],
        ]
        g = CorrelationSignalGenerator(client=mock_client)
        result = g.compute_from_db(today)
        assert result.lead_lag_component is not None
        assert abs(result.lead_lag_component) < 0.1

    def test_lead_lag_empty_returns_none_component(self, mock_client):
        today = date.today()
        mock_client.query.side_effect = [
            [(0.20, 0.60, "normal", 0.10, None, 0.35, today)],
            [],
        ]
        g = CorrelationSignalGenerator(client=mock_client)
        result = g.compute_from_db(today)
        assert result.lead_lag_component is None
