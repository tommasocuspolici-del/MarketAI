"""Tests for engine.market_data.fred_simple_client (v7.1.2)."""
from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from engine.market_data.fred_simple_client import (
    FredKeyMissingError,
    FredSimpleClient,
    FredSimpleError,
)


def _mock_response(payload: dict) -> MagicMock:
    """Costruisce un mock di urllib.urlopen response con un dato JSON."""
    body = json.dumps(payload).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = body
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def test_no_api_key_raises(monkeypatch):
    """Senza FRED_API_KEY in env e nessun api_key passato, fetch_series solleva.

    v7.1.3 (fix B6 di BUG_REPORT_v7.1.1.md): aggiungiamo monkeypatch.delenv
    per isolare il test dall'env reale dello sviluppatore. Il costruttore
    fa ``api_key or os.environ.get("FRED_API_KEY", "")`` quindi senza
    delenv la key reale dell'utente vincerebbe sul ``""`` passato.
    """
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    client = FredSimpleClient(api_key="")
    assert client.has_api_key is False
    with pytest.raises(FredKeyMissingError):
        client.fetch_series("DGS10")


def test_fetch_series_parses_observations():
    """Costruisce DataFrame da osservazioni FRED ben formate."""
    payload = {
        "observations": [
            {"date": "2026-01-15", "value": "4.32"},
            {"date": "2026-01-14", "value": "4.30"},
        ]
    }
    client = FredSimpleClient(api_key="dummy")
    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        df = client.fetch_series("DGS10")
    assert len(df) == 2
    assert list(df.columns) == ["ts", "value"]
    assert df.iloc[0]["value"] == pytest.approx(4.32)
    assert isinstance(df.iloc[0]["ts"], pd.Timestamp)


def test_fetch_series_filters_dot_values():
    """FRED usa '.' per dati mancanti — devono essere esclusi."""
    payload = {
        "observations": [
            {"date": "2026-01-15", "value": "4.32"},
            {"date": "2026-01-14", "value": "."},
            {"date": "2026-01-13", "value": "4.28"},
        ]
    }
    client = FredSimpleClient(api_key="dummy")
    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        df = client.fetch_series("DGS10")
    assert len(df) == 2
    assert all(v != "." for v in df["value"])


def test_fetch_series_empty_observations():
    """Lista vuota di observations -> DataFrame vuoto."""
    payload = {"observations": []}
    client = FredSimpleClient(api_key="dummy")
    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        df = client.fetch_series("UNKNOWN")
    assert df.empty


def test_fetch_latest_returns_first_row():
    """fetch_latest ritorna (date, valore) dell'ultima osservazione."""
    payload = {
        "observations": [
            {"date": "2026-01-15", "value": "4.32"},
        ]
    }
    client = FredSimpleClient(api_key="dummy")
    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        result = client.fetch_latest("DGS10")
    assert result is not None
    obs_date, value = result
    assert obs_date.isoformat() == "2026-01-15"
    assert value == pytest.approx(4.32)


def test_fetch_latest_returns_none_on_error():
    """Errore di rete -> None senza eccezione."""
    client = FredSimpleClient(api_key="dummy")
    with patch(
        "urllib.request.urlopen",
        side_effect=OSError("network down"),
    ):
        result = client.fetch_latest("DGS10")
    assert result is None


def test_fetch_yield_curve_aggregates_tenors():
    """fetch_yield_curve fa 8 chiamate (una per tenor) e aggrega risultati."""
    payload_per_tenor = {
        "observations": [{"date": "2026-01-15", "value": "4.20"}]
    }
    client = FredSimpleClient(api_key="dummy")
    # urlopen viene chiamato 1 volta per ogni tenor (8 in totale)
    with patch(
        "urllib.request.urlopen",
        return_value=_mock_response(payload_per_tenor),
    ):
        df = client.fetch_yield_curve()
    # 8 tenors disponibili: 1M, 3M, 6M, 1Y, 2Y, 5Y, 10Y, 30Y
    assert len(df) == 8
    assert set(df.columns) == {"tenor", "series_id", "yield_pct", "observation_date"}
    assert df["yield_pct"].iloc[0] == pytest.approx(4.20)


def test_fetch_yield_curve_skips_missing_tenors():
    """Tenors senza dati FRED non finiscono nel DataFrame finale."""
    empty_payload = {"observations": []}
    client = FredSimpleClient(api_key="dummy")
    with patch(
        "urllib.request.urlopen",
        return_value=_mock_response(empty_payload),
    ):
        df = client.fetch_yield_curve()
    assert df.empty
