"""Tests for E6_Macro page logic (v7.2 fix B5).

Test sulle funzioni pure (_classify_traffic_light, _classify_trend) e sul
fallback graceful quando FRED non risponde.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from presentation.dashboard_engine.pages.E6_Macro import (
    _classify_traffic_light,
    _classify_trend,
    _build_macro_rows,
)


# ─────────────────────────────────────────────────── traffic light
@pytest.mark.parametrize(
    "series_id, value, expected_emoji",
    [
        # CPI: green 0-2.5%, yellow -0.5..4, oltre rosso
        ("CPIAUCSL", 1.5, "🟢"),
        ("CPIAUCSL", 3.0, "🟡"),
        ("CPIAUCSL", 5.5, "🔴"),
        ("CPIAUCSL", -1.0, "🔴"),  # deflazione
        # UNRATE: green <5, yellow <7
        ("UNRATE", 3.5, "🟢"),
        ("UNRATE", 6.0, "🟡"),
        ("UNRATE", 8.0, "🔴"),
        # GDP Growth Rate (A191RL1Q225SBEA): green >=1.5, yellow >=0
        ("A191RL1Q225SBEA", 2.5, "🟢"),
        ("A191RL1Q225SBEA", 0.5, "🟡"),
        ("A191RL1Q225SBEA", -1.0, "🔴"),
        # 10Y: range fisiologico
        ("DGS10", 3.5, "🟢"),
        ("DGS10", 5.0, "🟡"),
        ("DGS10", 7.0, "🔴"),
    ],
)
def test_traffic_light_classification(series_id, value, expected_emoji):
    emoji, _ = _classify_traffic_light(series_id, value)
    assert emoji == expected_emoji


def test_traffic_light_unknown_series_returns_neutral():
    """Serie non in _TRAFFIC_LIGHTS → ⚪."""
    emoji, text = _classify_traffic_light("UNKNOWN", 42.0)
    assert emoji == "⚪"
    assert "configurate" in text.lower()


# ─────────────────────────────────────────────────── trend
@pytest.mark.parametrize(
    "delta, expected",
    [
        (0.5, "↑"),
        (-0.3, "↓"),
        (0.0001, "→"),  # sotto soglia rumore
        (-0.0001, "→"),
        (None, "—"),
    ],
)
def test_trend_classification(delta, expected):
    assert _classify_trend(delta) == expected


# ─────────────────────────────────────────────────── fetch fallback
def test_build_macro_rows_no_api_key_returns_unavailable():
    """Senza FRED_API_KEY, ritorna 5 righe tutte 'N/D' senza sollevare."""
    fake_client = MagicMock()
    fake_client.has_api_key = False

    with patch(
        "presentation.dashboard_engine.pages.E6_Macro.FredSimpleClient",
        return_value=fake_client,
    ):
        rows = _build_macro_rows()

    assert len(rows) == 5  # GDP, CPIAUCSL, UNRATE, FEDFUNDS, DGS10
    for r in rows:
        assert r["value"] is None
        assert r["status"] == "⚪"
        assert "non configurata" in r["status_text"].lower()


def test_build_macro_rows_with_data():
    """Con FRED che risponde, popola correttamente value/delta/status."""
    import pandas as pd

    fake_client = MagicMock()
    fake_client.has_api_key = True

    # 2 righe per serie già in % (UNRATE, FEDFUNDS, DGS10, GDP growth)
    _df_level = pd.DataFrame({
        "ts": pd.to_datetime(["2026-04-01", "2026-03-01"]),
        "value": [2.7, 2.5],
    })

    # 14 righe per CPIAUCSL (transform="yoy"): indice di livello in ordine desc.
    # iloc[-1]=102.7, iloc[-13]=100.0 → YoY = 2.7%
    # iloc[-2]=102.5, iloc[-14]=100.0 → prev_yoy = 2.5% → delta = 0.2%
    _cpi_ts = pd.date_range("2025-03-01", periods=14, freq="MS")  # oldest → newest
    _cpi_values = [100.0, 100.0] + [101.0] * 10 + [102.5, 102.7]
    _df_cpi = pd.DataFrame({
        "ts": _cpi_ts[::-1],                    # desc (come FRED sort_order=desc)
        "value": list(reversed(_cpi_values)),
    })

    def _side_effect(series_id, **kwargs):
        return _df_cpi if series_id == "CPIAUCSL" else _df_level

    fake_client.fetch_series.side_effect = _side_effect

    with patch(
        "presentation.dashboard_engine.pages.E6_Macro.FredSimpleClient",
        return_value=fake_client,
    ):
        rows = _build_macro_rows()

    assert len(rows) == 5
    cpi = next(r for r in rows if r["series_id"] == "CPIAUCSL")
    assert cpi["value"] == pytest.approx(2.7)
    assert cpi["delta"] == pytest.approx(0.2)  # latest_yoy - prev_yoy = 2.7 - 2.5
    # 2.7% è fuori green (0-2.5) ma dentro yellow (-0.5..4)
    assert cpi["status"] == "🟡"
    assert cpi["trend"] == "↑"  # delta positivo
