"""Test di non-regressione BUG-004.

BUG-004 (v7.2.2): _extract_kpi non usava _get_ticker_frame per estrarre il
sotto-frame di un singolo ticker da un DataFrame MultiIndex restituito da
yfinance >= 0.2.x. Risultato: tutti i KPI avevano lo stesso valore (primo
ticker del MultiIndex) invece di valori distinti per ticker.

Fix: _get_ticker_frame con xs(ticker, level=1) per il formato (field, ticker)
e data[ticker] per il formato (ticker, field). Ora in kpi_computer.KpiComputer.
"""
from __future__ import annotations

import pandas as pd
import pytest

from engine.market_data.kpi_computer import KpiComputer, MarketKpi

pytestmark = pytest.mark.regression

# Prezzi fixture: valori arbitrari ma distinti, non zero
_SP500_PRICE  = 5_250.0
_VIX_PRICE    = 18.5
_DXY_PRICE    = 104.2


@pytest.fixture()
def multiindex_df_field_ticker() -> pd.DataFrame:
    """DataFrame con MultiIndex (field, ticker) — formato yfinance >= 0.2.x."""
    tickers = ["^GSPC", "^VIX", "DX-Y.NYB"]
    idx = pd.date_range("2026-05-12", periods=3, freq="D")
    close_data = {
        "^GSPC":    [5200.0, 5230.0, _SP500_PRICE],
        "^VIX":     [20.0,   19.0,   _VIX_PRICE],
        "DX-Y.NYB": [103.0,  103.8,  _DXY_PRICE],
    }
    close_df = pd.DataFrame(close_data, index=idx)
    # Costruisce MultiIndex (field, ticker)
    arrays = [["Close"] * 3, tickers]
    close_df.columns = pd.MultiIndex.from_arrays(arrays)
    return close_df


@pytest.fixture()
def multiindex_df_ticker_field() -> pd.DataFrame:
    """DataFrame con MultiIndex (ticker, field) — formato yfinance legacy."""
    tickers = ["^GSPC", "^VIX", "DX-Y.NYB"]
    idx = pd.date_range("2026-05-12", periods=3, freq="D")
    frames = {}
    prices = {"^GSPC": _SP500_PRICE, "^VIX": _VIX_PRICE, "DX-Y.NYB": _DXY_PRICE}
    for t in tickers:
        frames[t] = pd.DataFrame({"Close": [prices[t] - 1, prices[t]]}, index=idx[:2])
    df = pd.concat(frames, axis=1)
    return df


def _make_kpi_computer() -> KpiComputer:
    """KpiComputer minimale con stub override/sanity/cache."""
    from unittest.mock import MagicMock
    override_store = MagicMock()
    override_store.resolve.side_effect = lambda kind, term, price: (price, False)
    sanity = MagicMock()
    sanity.check_price_data.return_value = []
    sanity.is_safe_to_store.return_value = True
    return KpiComputer(
        override_store=override_store,
        sanity=sanity,
        get_ws_price_fn=lambda t: None,
        lookup_cached_fn=lambda t: None,
    )


# ─── BUG-004: get_ticker_frame ────────────────────────────────────────────────

class TestGetTickerFrameMultiIndex:
    def test_field_ticker_format_returns_per_ticker_frame(self, multiindex_df_field_ticker):
        """BUG-004: formato (field, ticker) → xs(ticker, level=1) restituisce il frame corretto."""
        frame_sp500 = KpiComputer.get_ticker_frame(multiindex_df_field_ticker, "^GSPC")
        frame_vix   = KpiComputer.get_ticker_frame(multiindex_df_field_ticker, "^VIX")

        assert frame_sp500 is not None, "BUG-004: get_ticker_frame non deve restituire None"
        assert frame_vix   is not None, "BUG-004: get_ticker_frame non deve restituire None"
        assert float(frame_sp500["Close"].iloc[-1]) == pytest.approx(_SP500_PRICE)
        assert float(frame_vix["Close"].iloc[-1])   == pytest.approx(_VIX_PRICE)

    def test_field_ticker_sp500_and_vix_are_different(self, multiindex_df_field_ticker):
        """BUG-004: ticker diversi devono restituire frame con valori distinti."""
        frame_sp500 = KpiComputer.get_ticker_frame(multiindex_df_field_ticker, "^GSPC")
        frame_vix   = KpiComputer.get_ticker_frame(multiindex_df_field_ticker, "^VIX")
        assert float(frame_sp500["Close"].iloc[-1]) != float(frame_vix["Close"].iloc[-1]), \
            "BUG-004: tutti i KPI non devono avere lo stesso valore"

    def test_ticker_field_format_returns_correct_frame(self, multiindex_df_ticker_field):
        """BUG-004: formato (ticker, field) — vecchio formato legacy."""
        frame = KpiComputer.get_ticker_frame(multiindex_df_ticker_field, "^GSPC")
        assert frame is not None
        assert "Close" in frame.columns

    def test_unknown_ticker_returns_none(self, multiindex_df_field_ticker):
        """BUG-004: ticker non presente nel DataFrame restituisce None."""
        result = KpiComputer.get_ticker_frame(multiindex_df_field_ticker, "UNKNOWN_TICKER")
        assert result is None

    def test_none_data_returns_none(self):
        """BUG-004: dati None restituiscono None senza eccezioni."""
        assert KpiComputer.get_ticker_frame(None, "^GSPC") is None


# ─── BUG-004: extract_kpi con MultiIndex ─────────────────────────────────────

class TestExtractKpiMultiIndex:
    def test_sp500_and_vix_have_different_values(self, multiindex_df_field_ticker):
        """BUG-004: con MultiIndex, SP500 e VIX devono avere valori diversi."""
        computer = _make_kpi_computer()
        kpi_sp500 = computer.extract_kpi(
            data=multiindex_df_field_ticker, term="S&P 500",
            yf_ticker="^GSPC", currency="USD", fmt=",.2f",
        )
        kpi_vix = computer.extract_kpi(
            data=multiindex_df_field_ticker, term="VIX",
            yf_ticker="^VIX", currency="USD", fmt=".2f",
        )
        assert kpi_sp500.value is not None, "BUG-004: valore SP500 non deve essere None"
        assert kpi_vix.value is not None,   "BUG-004: valore VIX non deve essere None"
        assert kpi_sp500.value != kpi_vix.value, \
            "BUG-004: SP500 e VIX devono avere valori distinti nel MultiIndex"

    def test_sp500_value_matches_fixture(self, multiindex_df_field_ticker):
        """BUG-004: il valore estratto corrisponde al prezzo nell'ultima riga del fixture."""
        computer = _make_kpi_computer()
        kpi = computer.extract_kpi(
            data=multiindex_df_field_ticker, term="S&P 500",
            yf_ticker="^GSPC", currency="USD", fmt=",.2f",
        )
        assert kpi.value == pytest.approx(_SP500_PRICE, rel=1e-4)

    def test_kpi_has_no_error_on_valid_data(self, multiindex_df_field_ticker):
        """BUG-004: estrazione da dati validi non deve produrre errore."""
        computer = _make_kpi_computer()
        kpi = computer.extract_kpi(
            data=multiindex_df_field_ticker, term="DXY",
            yf_ticker="DX-Y.NYB", currency="USD", fmt=".2f",
        )
        assert kpi.error == "", f"BUG-004: errore inatteso: {kpi.error!r}"
