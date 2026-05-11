"""Tests for engine.market_data.fetch_delta_windows (v7.2 fix B10).

Test del fallback graceful (yfinance non installato o ticker errato);
NON test di integrazione live (richiederebbe rete).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engine.market_data.live_market_service import (
    DeltaWindow,
    fetch_delta_windows,
)


def test_delta_window_dataclass_immutable():
    """DeltaWindow e' frozen."""
    w = DeltaWindow(
        term="Test",
        ticker="X",
        delta_1w=0.01,
        delta_1m=0.02,
        delta_ytd=0.03,
    )
    with pytest.raises((AttributeError, Exception)):
        w.delta_1w = 0.99  # type: ignore[misc]


def test_delta_window_optional_last_price():
    """last_price ha default None."""
    w = DeltaWindow(
        term="Test",
        ticker="X",
        delta_1w=None,
        delta_1m=None,
        delta_ytd=None,
    )
    assert w.last_price is None
    assert w.error == ""


def test_fetch_delta_windows_no_yfinance_returns_unavailable(monkeypatch):
    """Senza yfinance installato, ritorna lista con error chiaro."""
    # Simula yfinance assente
    import sys

    monkeypatch.setitem(sys.modules, "yfinance", None)

    with patch.dict(sys.modules, {"yfinance": None}):
        # Forziamo ImportError facendo finta che yfinance.download non esista
        # Il modo piu' pulito: rinomina temporaneamente yfinance via sys.modules
        # Nota: usiamo un approccio diverso — patchiamo l'import dentro la funzione
        windows = fetch_delta_windows([("SPY", "S&P 500")])

    assert len(windows) == 1
    assert windows[0].term == "S&P 500"
    assert windows[0].ticker == "SPY"
    # Tutti i delta None (sia se yfinance manca, sia se download fallisce)
    assert windows[0].delta_1w is None
    assert windows[0].delta_1m is None
    assert windows[0].delta_ytd is None


def test_fetch_delta_windows_empty_data_handled():
    """yfinance ritorna DataFrame vuoto -> DeltaWindow con error."""
    import pandas as pd

    fake_yf = MagicMock()
    fake_yf.download.return_value = pd.DataFrame()  # vuoto

    import sys

    with patch.dict(sys.modules, {"yfinance": fake_yf}):
        windows = fetch_delta_windows([("FAKE", "Fake Ticker")])

    assert len(windows) == 1
    assert windows[0].delta_1w is None
    assert windows[0].error  # presente


def test_fetch_delta_windows_computes_deltas_from_close():
    """Dato un DataFrame Close coerente, calcola correttamente i delta."""
    import sys

    import pandas as pd

    # Creo un anno di prezzi: 252 trading days con prezzo che sale linearmente
    # da 100 a 200. Cosi' 1W (5 day fa) ≈ 1.95% (a fine), 1M (~21d) ≈ 8.3%.
    dates = pd.date_range("2025-05-01", periods=252, freq="B", tz="UTC")
    close_values = [100.0 + (i / 251.0) * 100.0 for i in range(252)]
    df = pd.DataFrame({"Close": close_values}, index=dates)

    fake_yf = MagicMock()
    fake_yf.download.return_value = df

    with patch.dict(sys.modules, {"yfinance": fake_yf}):
        windows = fetch_delta_windows([("TEST", "Test Asset")])

    assert len(windows) == 1
    w = windows[0]
    assert w.error == ""
    assert w.last_price == pytest.approx(200.0)
    # 1W: prezzo a -5 / -1 day fa
    # close[-6] = 100 + (246/251)*100 ≈ 198.0
    # 1W delta = (200 - 198.0) / 198.0 ≈ 0.0101
    assert w.delta_1w is not None
    assert 0.005 < w.delta_1w < 0.025
    # 1M: prezzo a -22 day
    # close[-22] = 100 + (230/251)*100 ≈ 191.6
    # 1M delta = (200 - 191.6) / 191.6 ≈ 0.0438
    assert w.delta_1m is not None
    assert 0.03 < w.delta_1m < 0.06


def test_fetch_delta_windows_handles_short_history():
    """Storico < 21 giorni → 1M delta None ma 1W puo' essere calcolato."""
    import sys

    import pandas as pd

    dates = pd.date_range("2025-05-01", periods=10, freq="B", tz="UTC")
    df = pd.DataFrame({"Close": [100.0 + i for i in range(10)]}, index=dates)

    fake_yf = MagicMock()
    fake_yf.download.return_value = df

    with patch.dict(sys.modules, {"yfinance": fake_yf}):
        windows = fetch_delta_windows([("SHORT", "Short History")])

    assert len(windows) == 1
    w = windows[0]
    # 10 giorni > 5 → 1W disponibile
    assert w.delta_1w is not None
    # 10 giorni < 21 → 1M None
    assert w.delta_1m is None
