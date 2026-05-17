"""Tests for IBSignalGenerator (Fase 8 DoD)."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from engine.ib_forecast.ib_signal_generator import IBSignalGenerator, _value_to_signal
from engine.ib_forecast.schemas import IBConsensus, IBSignal


# ── _value_to_signal unit tests ───────────────────────────────────────────────

def test_value_to_signal_gdp_bull():
    rules = {"bull_above": 2.5, "bear_below": 0.5, "inverted": False}
    assert _value_to_signal(3.0, rules) == 1.0


def test_value_to_signal_gdp_bear():
    rules = {"bull_above": 2.5, "bear_below": 0.5, "inverted": False}
    assert _value_to_signal(0.0, rules) == -1.0


def test_value_to_signal_gdp_mid():
    rules = {"bull_above": 2.5, "bear_below": 0.5, "inverted": False}
    sig = _value_to_signal(1.5, rules)
    assert -1.0 <= sig <= 1.0


def test_value_to_signal_cpi_inverted_high_is_bear():
    rules = {"bull_above": 0.0, "bear_below": 4.0, "inverted": True}
    assert _value_to_signal(5.0, rules) == -1.0


def test_value_to_signal_cpi_inverted_low_is_bull():
    rules = {"bull_above": 0.0, "bear_below": 4.0, "inverted": True}
    assert _value_to_signal(-0.5, rules) == 1.0


# ── IBSignalGenerator tests ───────────────────────────────────────────────────

@pytest.fixture()
def mock_client():
    client = MagicMock()
    client.execute = MagicMock()
    client.query = MagicMock(return_value=[])
    return client


def _make_consensus(indicator: str, value: float) -> IBConsensus:
    return IBConsensus(
        indicator=indicator,
        horizon="2025",
        consensus_value=value,
        source_count=2,
    )


def test_generate_empty_list(mock_client):
    gen = IBSignalGenerator(client=mock_client)
    result = gen.generate([])
    assert result is None


def test_generate_returns_signal_in_range(mock_client):
    consensus = [
        _make_consensus("GDP",      2.8),
        _make_consensus("CPI",      2.1),
        _make_consensus("FEDFUNDS", 4.5),
    ]
    gen = IBSignalGenerator(client=mock_client)
    signal = gen.generate(consensus)
    assert signal is not None
    assert -1.0 <= signal.score <= 1.0
    assert isinstance(signal.signal_date, datetime)


def test_generate_bullish_scenario(mock_client):
    consensus = [
        _make_consensus("GDP",      4.0),   # bull
        _make_consensus("CPI",      1.5),   # low inflation = bull
        _make_consensus("FEDFUNDS", 1.0),   # low rates = bull
    ]
    gen = IBSignalGenerator(client=mock_client)
    signal = gen.generate(consensus)
    assert signal is not None
    assert signal.score > 0.0


def test_generate_bearish_scenario(mock_client):
    consensus = [
        _make_consensus("GDP",      -0.5),  # contraction
        _make_consensus("CPI",       6.0),  # high inflation = bear
        _make_consensus("FEDFUNDS",  6.0),  # high rates = bear
    ]
    gen = IBSignalGenerator(client=mock_client)
    signal = gen.generate(consensus)
    assert signal is not None
    assert signal.score < 0.0


def test_generate_persists_to_db(mock_client):
    consensus = [_make_consensus("GDP", 2.5)]
    gen = IBSignalGenerator(client=mock_client)
    gen.generate(consensus)
    mock_client.execute.assert_called_once()


def test_generate_with_consensus_low_averages(mock_client):
    cons = IBConsensus(
        indicator="GDP",
        horizon="2025",
        consensus_value=3.0,
        consensus_low=0.3,   # pessimistic scenario pulls score down
        source_count=3,
    )
    gen = IBSignalGenerator(client=mock_client)
    signal = gen.generate([cons])
    assert signal is not None
    # With low = 0.3 (bear), score should be less than pure bull (3.0)
    pure_bull = IBSignalGenerator(client=mock_client).generate(
        [IBConsensus(indicator="GDP", horizon="2025", consensus_value=3.0, source_count=1)]
    )
    assert pure_bull is not None
    assert signal.score <= pure_bull.score


def test_read_latest_returns_none_when_empty(mock_client):
    gen = IBSignalGenerator(client=mock_client)
    result = gen.read_latest()
    assert result is None


def test_data_quality_partial_when_few_components(mock_client):
    consensus = [_make_consensus("GDP", 2.5)]  # only 1 component
    gen = IBSignalGenerator(client=mock_client)
    signal = gen.generate(consensus)
    assert signal is not None
    assert signal.data_quality == "partial"


def test_data_quality_ok_when_enough_components(mock_client):
    consensus = [
        _make_consensus("GDP",      2.5),
        _make_consensus("CPI",      2.0),
        _make_consensus("FEDFUNDS", 4.5),
    ]
    gen = IBSignalGenerator(client=mock_client)
    signal = gen.generate(consensus)
    assert signal is not None
    assert signal.data_quality == "ok"
