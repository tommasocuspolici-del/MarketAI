"""Tests EarningsCalendarFetcher — fetch yfinance calendar + earnings_dates."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from engine.market_data.fetchers.earnings_calendar_fetcher import (
    EarningsCalendarFetcher,
    _deduplicate,
    _extract_date,
    _float_or_none,
    _parse_calendar,
    _parse_earnings_dates,
    _validate,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def mock_client():
    client = MagicMock()
    client.query.return_value = []
    client.execute.return_value = None
    return client


@pytest.fixture()
def fetcher(mock_client):
    return EarningsCalendarFetcher(client=mock_client)


def _make_ticker_mock(
    calendar: dict | None = None,
    earnings_dates: pd.DataFrame | None = None,
    info: dict | None = None,
):
    t = MagicMock()
    t.calendar = calendar
    t.earnings_dates = earnings_dates if earnings_dates is not None else pd.DataFrame()
    t.info = info or {"shortName": "Acme Corp"}
    return t


def _future_date(days: int = 10) -> date:
    return date.today() + timedelta(days=days)


def _past_date(days: int = 30) -> date:
    return date.today() - timedelta(days=days)


# ─── Init ─────────────────────────────────────────────────────────────────────

class TestInit:
    def test_stores_client(self, mock_client):
        f = EarningsCalendarFetcher(client=mock_client)
        assert f._client is mock_client


# ─── fetch_and_persist ────────────────────────────────────────────────────────

class TestFetchAndPersist:
    def test_returns_int(self, fetcher):
        with patch("yfinance.Ticker") as MockTicker:
            MockTicker.return_value = _make_ticker_mock(
                calendar={"Earnings Date": _future_date()}
            )
            result = fetcher.fetch_and_persist(["AAPL"])
        assert isinstance(result, int)

    def test_empty_tickers_returns_zero(self, fetcher):
        result = fetcher.fetch_and_persist([])
        assert result == 0

    def test_calls_execute_on_valid_calendar(self, mock_client):
        with patch("yfinance.Ticker") as MockTicker:
            MockTicker.return_value = _make_ticker_mock(
                calendar={"Earnings Date": _future_date()}
            )
            EarningsCalendarFetcher(client=mock_client).fetch_and_persist(["AAPL"])
        assert mock_client.execute.called

    def test_no_crash_on_yfinance_error(self, fetcher):
        with patch("yfinance.Ticker", side_effect=RuntimeError("network")):
            result = fetcher.fetch_and_persist(["AAPL"])
        assert result == 0

    def test_aggregates_multiple_tickers(self, mock_client):
        with patch("yfinance.Ticker") as MockTicker:
            MockTicker.return_value = _make_ticker_mock(
                calendar={"Earnings Date": _future_date()}
            )
            f = EarningsCalendarFetcher(client=mock_client)
            result = f.fetch_and_persist(["AAPL", "NVDA", "MSFT"])
        # Almeno 1 riga per ticker (3 ticker × 1 data ciascuno)
        assert result >= 3

    def test_no_data_returns_zero(self, fetcher):
        with patch("yfinance.Ticker") as MockTicker:
            MockTicker.return_value = _make_ticker_mock(calendar=None)
            result = fetcher.fetch_and_persist(["AAPL"])
        assert result == 0


# ─── get_upcoming ─────────────────────────────────────────────────────────────

class TestGetUpcoming:
    def test_returns_dataframe(self, fetcher):
        df = fetcher.get_upcoming()
        assert isinstance(df, pd.DataFrame)

    def test_returns_empty_on_db_error(self, mock_client):
        mock_client.query.side_effect = Exception("DB error")
        f = EarningsCalendarFetcher(client=mock_client)
        df = f.get_upcoming()
        assert df.empty

    def test_returns_data_from_db(self, mock_client):
        mock_client.query.return_value = [
            ("AAPL", "Apple Inc", _future_date(), "AMC",
             1.50, 90_000_000_000.0, None, None, None, "Q2 2026")
        ]
        f = EarningsCalendarFetcher(client=mock_client)
        df = f.get_upcoming(days=30)
        assert len(df) == 1
        assert df["ticker"].iloc[0] == "AAPL"

    def test_has_expected_columns(self, fetcher):
        df = fetcher.get_upcoming()
        expected = {"ticker", "company_name", "report_date", "report_time",
                    "eps_estimate", "revenue_estimate", "eps_actual",
                    "revenue_actual", "eps_surprise_pct", "fiscal_period"}
        assert expected.issubset(set(df.columns))


# ─── get_historical ───────────────────────────────────────────────────────────

class TestGetHistorical:
    def test_returns_dataframe(self, fetcher):
        df = fetcher.get_historical("AAPL")
        assert isinstance(df, pd.DataFrame)

    def test_returns_empty_on_db_error(self, mock_client):
        mock_client.query.side_effect = Exception("DB")
        f = EarningsCalendarFetcher(client=mock_client)
        df = f.get_historical("AAPL")
        assert df.empty


# ─── _parse_calendar ──────────────────────────────────────────────────────────

class TestParseCalendar:
    def test_dict_with_valid_date(self):
        ticker_obj = _make_ticker_mock(
            calendar={"Earnings Date": _future_date(), "Earnings Average": 1.50}
        )
        rows = _parse_calendar(ticker_obj, "AAPL", "Apple Inc")
        assert len(rows) == 1
        assert rows[0]["ticker"] == "AAPL"
        assert rows[0]["eps_estimate"] == 1.50

    def test_dict_no_date_returns_empty(self):
        ticker_obj = _make_ticker_mock(calendar={"Earnings Average": 1.50})
        rows = _parse_calendar(ticker_obj, "AAPL", "Apple Inc")
        assert rows == []

    def test_none_calendar_returns_empty(self):
        ticker_obj = _make_ticker_mock(calendar=None)
        rows = _parse_calendar(ticker_obj, "AAPL", None)
        assert rows == []

    def test_exception_in_calendar_returns_empty(self):
        ticker_obj = MagicMock()
        ticker_obj.calendar = property(lambda self: (_ for _ in ()).throw(RuntimeError()))
        # Deve gestire l'eccezione gracefully
        rows = _parse_calendar(ticker_obj, "AAPL", None)
        assert isinstance(rows, list)

    def test_date_as_list(self):
        ticker_obj = _make_ticker_mock(
            calendar={"Earnings Date": [_future_date(), _future_date(20)]}
        )
        rows = _parse_calendar(ticker_obj, "TSLA", None)
        assert len(rows) == 1  # prende solo il primo


# ─── _parse_earnings_dates ────────────────────────────────────────────────────

class TestParseEarningsDates:
    def _make_ed_df(self, d: date, eps_est=1.0, eps_act=1.1, surprise=10.0):
        idx = pd.DatetimeIndex([pd.Timestamp(d)])
        return pd.DataFrame(
            {"EPS Estimate": [eps_est], "Reported EPS": [eps_act], "Surprise(%)": [surprise]},
            index=idx,
        )

    def test_parses_valid_row(self):
        ticker_obj = _make_ticker_mock(earnings_dates=self._make_ed_df(_past_date(10)))
        rows = _parse_earnings_dates(ticker_obj, "AAPL", "Apple Inc")
        assert len(rows) == 1
        assert rows[0]["eps_estimate"] == 1.0
        assert rows[0]["eps_actual"] == 1.1
        assert rows[0]["eps_surprise_pct"] == 10.0

    def test_skips_old_dates(self):
        ticker_obj = _make_ticker_mock(earnings_dates=self._make_ed_df(_past_date(400)))
        rows = _parse_earnings_dates(ticker_obj, "AAPL", None)
        assert rows == []

    def test_skips_far_future_dates(self):
        ticker_obj = _make_ticker_mock(earnings_dates=self._make_ed_df(_future_date(120)))
        rows = _parse_earnings_dates(ticker_obj, "AAPL", None)
        assert rows == []

    def test_empty_df_returns_empty(self):
        ticker_obj = _make_ticker_mock(earnings_dates=pd.DataFrame())
        rows = _parse_earnings_dates(ticker_obj, "AAPL", None)
        assert rows == []


# ─── _deduplicate ─────────────────────────────────────────────────────────────

class TestDeduplicate:
    def test_keeps_most_complete_row(self):
        df = pd.DataFrame([
            {"ticker": "AAPL", "report_date": date(2026, 5, 1),
             "eps_estimate": None, "eps_actual": None},
            {"ticker": "AAPL", "report_date": date(2026, 5, 1),
             "eps_estimate": 1.5, "eps_actual": 1.6},
        ])
        result = _deduplicate(df)
        assert len(result) == 1
        assert result["eps_estimate"].iloc[0] == 1.5

    def test_different_dates_kept(self):
        df = pd.DataFrame([
            {"ticker": "AAPL", "report_date": date(2026, 2, 1), "eps_estimate": 1.0},
            {"ticker": "AAPL", "report_date": date(2026, 5, 1), "eps_estimate": 1.5},
        ])
        result = _deduplicate(df)
        assert len(result) == 2

    def test_empty_df_returned_unchanged(self):
        df = pd.DataFrame()
        result = _deduplicate(df)
        assert result.empty


# ─── _validate ────────────────────────────────────────────────────────────────

class TestValidate:
    def test_valid_df_no_exception(self):
        df = pd.DataFrame([{"ticker": "AAPL", "report_date": date(2026, 5, 1)}])
        _validate(df)  # non deve lanciare

    def test_missing_ticker_raises(self):
        df = pd.DataFrame([{"report_date": date(2026, 5, 1)}])
        with pytest.raises(ValueError, match="ticker"):
            _validate(df)

    def test_null_ticker_raises(self):
        df = pd.DataFrame([{"ticker": None, "report_date": date(2026, 5, 1)}])
        with pytest.raises(ValueError):
            _validate(df)

    def test_null_report_date_raises(self):
        df = pd.DataFrame([{"ticker": "AAPL", "report_date": None}])
        with pytest.raises(ValueError, match="report_date"):
            _validate(df)


# ─── helpers ──────────────────────────────────────────────────────────────────

class TestExtractDate:
    def test_date_passthrough(self):
        d = date(2026, 5, 21)
        assert _extract_date(d) == d

    def test_timestamp(self):
        ts = pd.Timestamp("2026-05-21")
        assert _extract_date(ts) == date(2026, 5, 21)

    def test_string(self):
        assert _extract_date("2026-05-21") == date(2026, 5, 21)

    def test_list_takes_first(self):
        assert _extract_date([date(2026, 5, 21), date(2026, 8, 21)]) == date(2026, 5, 21)

    def test_none_returns_none(self):
        assert _extract_date(None) is None

    def test_invalid_string_returns_none(self):
        assert _extract_date("not-a-date") is None


class TestFloatOrNone:
    def test_valid_float(self):
        assert _float_or_none(1.5) == 1.5

    def test_string_float(self):
        assert _float_or_none("2.3") == 2.3

    def test_none_returns_none(self):
        assert _float_or_none(None) is None

    def test_nan_returns_none(self):
        import math
        assert _float_or_none(float("nan")) is None

    def test_invalid_string_returns_none(self):
        assert _float_or_none("N/A") is None
