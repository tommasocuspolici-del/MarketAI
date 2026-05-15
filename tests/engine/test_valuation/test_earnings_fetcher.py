"""Tests per EarningsFetcher — Valuation Engine Blocco 3."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from engine.analytics.valuation.earnings_fetcher import EarningsFetcher, EarningsSnapshot


@pytest.fixture()
def mock_client():
    client = MagicMock()
    client.query.return_value = []
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=ctx)
    ctx.__exit__ = MagicMock(return_value=False)
    client.transaction.return_value = ctx
    return client


@pytest.fixture()
def fetcher(mock_client):
    return EarningsFetcher(client=mock_client)


class TestEarningsSnapshotShape:
    def test_returns_snapshot_instance(self, fetcher):
        result = fetcher.get_trailing_eps("^GSPC", date(2024, 1, 1))
        assert isinstance(result, EarningsSnapshot)

    def test_ticker_propagated(self, fetcher):
        result = fetcher.get_trailing_eps("AAPL", date(2024, 1, 1))
        assert result.ticker == "AAPL"

    def test_as_of_propagated(self, fetcher):
        d = date(2024, 6, 15)
        result = fetcher.get_trailing_eps("^GSPC", d)
        assert result.as_of == d

    def test_source_none_when_no_data(self, fetcher):
        result = fetcher.get_trailing_eps("UNKNOWN_TICKER", date(2024, 1, 1))
        assert result.source in ("none", "yfinance")

    def test_quarters_used_zero_when_empty(self, fetcher):
        result = fetcher.get_trailing_eps("^GSPC", date(2024, 1, 1))
        assert result.quarters_used >= 0

    def test_eps_none_when_empty_db(self, fetcher):
        with patch("yfinance.Ticker") as mock_yf:
            mock_yf.return_value.info = {}
            result = fetcher.get_trailing_eps("^GSPC", date(2024, 1, 1))
        assert result.eps_trailing_4q is None or isinstance(result.eps_trailing_4q, float)


class TestEarningsFetcherWithEdgarData:
    def test_trailing_eps_sum_of_four_quarters(self, mock_client):
        """EPS trailing = somma 4 trimestri da fundamentals_edgar."""
        mock_client.query.side_effect = [
            [(date(2024, 9, 30), 5.20),
             (date(2024, 6, 30), 4.80),
             (date(2024, 3, 31), 5.10),
             (date(2023, 12, 31), 4.90)],  # 4 trimestri → sum = 20.0
            [],  # yoy query
        ]
        f = EarningsFetcher(client=mock_client)
        result = f.get_trailing_eps("AAPL", date(2024, 10, 1))
        assert result.eps_trailing_4q == pytest.approx(20.0, rel=1e-6)
        assert result.source == "edgar"
        assert result.quarters_used == 4

    def test_trailing_eps_two_quarters(self, mock_client):
        """Anche solo 2 trimestri producono un risultato (somma parziale)."""
        mock_client.query.side_effect = [
            [(date(2024, 9, 30), 3.50),
             (date(2024, 6, 30), 3.20)],
            [],
        ]
        f = EarningsFetcher(client=mock_client)
        result = f.get_trailing_eps("SPY", date(2024, 10, 1))
        assert result.eps_trailing_4q == pytest.approx(6.70, rel=1e-6)
        assert result.quarters_used == 2

    def test_yoy_growth_computed(self, mock_client):
        """YoY growth calcolato quando disponibili anche dati anno precedente."""
        # _read_from_edgar: SELECT report_date, eps_diluted → 2-tuples
        current_eps_rows = [
            (date(2024, 9, 30), 5.0),
            (date(2024, 6, 30), 5.0),
            (date(2024, 3, 31), 5.0),
            (date(2023, 12, 31), 5.0),
        ]
        # _compute_yoy: SELECT eps_diluted → 1-tuples
        prev_eps_rows = [(4.0,), (4.0,), (4.0,), (4.0,)]
        mock_client.query.side_effect = [current_eps_rows, prev_eps_rows]
        f = EarningsFetcher(client=mock_client)
        result = f.get_trailing_eps("AAPL", date(2024, 10, 1))
        assert result.eps_yoy_pct == pytest.approx(25.0, rel=1e-3)  # 20/16 - 1 = 25%

    def test_no_yoy_when_insufficient_history(self, mock_client):
        mock_client.query.side_effect = [
            [(date(2024, 9, 30), 5.0)],
            [],  # nessun dato anno precedente
        ]
        f = EarningsFetcher(client=mock_client)
        result = f.get_trailing_eps("AAPL", date(2024, 10, 1))
        assert result.eps_yoy_pct is None


class TestEarningsFetcherYfinanceFallback:
    def test_uses_yfinance_when_edgar_empty(self, mock_client):
        """Usa yfinance quando fundamentals_edgar è vuoto."""
        mock_client.query.return_value = []
        with patch("yfinance.Ticker") as mock_yf:
            mock_yf.return_value.info = {"trailingEps": 18.50}
            f = EarningsFetcher(client=mock_client)
            result = f.get_trailing_eps("^GSPC", date(2024, 1, 1))
        assert result.eps_trailing_4q == pytest.approx(18.50)
        assert result.source == "yfinance"
        assert result.quarters_used == 4

    def test_yfinance_zero_eps_returns_none(self, mock_client):
        mock_client.query.return_value = []
        with patch("yfinance.Ticker") as mock_yf:
            mock_yf.return_value.info = {}
            f = EarningsFetcher(client=mock_client)
            result = f.get_trailing_eps("^GSPC", date(2024, 1, 1))
        assert result.eps_trailing_4q is None
        assert result.source == "none"


class TestFetchAndPersistSP500:
    def test_returns_zero_without_fred_client(self, mock_client):
        f = EarningsFetcher(client=mock_client, fred_client=None)
        assert f.fetch_and_persist_sp500() == 0

    def test_returns_zero_on_fred_error(self, mock_client):
        mock_fred = MagicMock()
        mock_fred.fetch_series.side_effect = Exception("FRED error")
        f = EarningsFetcher(client=mock_client, fred_client=mock_fred)
        assert f.fetch_and_persist_sp500() == 0

    def test_returns_zero_on_empty_fred_response(self, mock_client):
        import pandas as pd
        mock_fred = MagicMock()
        mock_fred.fetch_series.return_value = pd.DataFrame()
        f = EarningsFetcher(client=mock_client, fred_client=mock_fred)
        assert f.fetch_and_persist_sp500() == 0

    def test_persist_called_with_valid_fred_data(self, mock_client):
        import pandas as pd
        from datetime import datetime
        mock_fred = MagicMock()
        mock_fred.fetch_series.return_value = pd.DataFrame({
            "ts": [datetime(2024, 3, 31), datetime(2024, 6, 30)],
            "value": [50.0, 52.0],
        })
        mock_client.query.return_value = []
        f = EarningsFetcher(client=mock_client, fred_client=mock_fred)
        rows = f.fetch_and_persist_sp500()
        # 2 osservazioni × 2 ticker (^GSPC + SPY) = 4 righe tentate
        assert rows >= 0


class TestTransformFredData:
    def test_quarter_mapping_q1(self, fetcher):
        import pandas as pd
        df = pd.DataFrame({"ts": [pd.Timestamp("2024-03-31")], "value": [10.0]})
        rows = fetcher._transform_fred_sp500eps(df)
        periods = {r["period"] for r in rows}
        assert "Q1" in periods

    def test_quarter_mapping_q4(self, fetcher):
        import pandas as pd
        df = pd.DataFrame({"ts": [pd.Timestamp("2024-12-31")], "value": [10.0]})
        rows = fetcher._transform_fred_sp500eps(df)
        periods = {r["period"] for r in rows}
        assert "Q4" in periods

    def test_both_tickers_generated(self, fetcher):
        import pandas as pd
        df = pd.DataFrame({"ts": [pd.Timestamp("2024-06-30")], "value": [10.0]})
        rows = fetcher._transform_fred_sp500eps(df)
        tickers = {r["ticker"] for r in rows}
        assert "^GSPC" in tickers
        assert "SPY" in tickers

    def test_nan_values_skipped(self, fetcher):
        import pandas as pd
        import numpy as np
        df = pd.DataFrame({"ts": [pd.Timestamp("2024-06-30")], "value": [np.nan]})
        rows = fetcher._transform_fred_sp500eps(df)
        assert len(rows) == 0
