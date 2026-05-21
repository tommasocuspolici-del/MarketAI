"""Tests OptionsFlowFetcher — fetch yfinance option chain → putcall_ratio_daily."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from engine.market_data.fetchers.options_flow_fetcher import (
    OptionsFlowFetcher,
    _compute_iv_atm,
    _compute_iv_skew,
    _compute_metrics,
    _f,
    _get_spot,
    _int_or_none,
    _otm_ivs,
    _safe_options,
    _sum_col,
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
    return OptionsFlowFetcher(client=mock_client)


def _make_chain_df(strikes, ivs, volumes, oi_values):
    return pd.DataFrame({
        "strike": strikes,
        "impliedVolatility": ivs,
        "volume": volumes,
        "openInterest": oi_values,
    })


def _make_ticker_mock(
    options=("2026-06-20",),
    calls=None,
    puts=None,
    spot=500.0,
):
    t = MagicMock()
    t.options = options
    chain = MagicMock()
    chain.calls = calls if calls is not None else _make_chain_df(
        [480, 490, 500, 510, 520],
        [0.20, 0.18, 0.17, 0.18, 0.19],
        [100, 200, 500, 200, 100],
        [500, 1000, 2000, 1000, 500],
    )
    chain.puts = puts if puts is not None else _make_chain_df(
        [480, 490, 500, 510, 520],
        [0.22, 0.20, 0.17, 0.16, 0.15],
        [150, 250, 600, 250, 150],
        [600, 1200, 2500, 1200, 600],
    )
    t.option_chain.return_value = chain
    t.info = {"regularMarketPrice": spot}
    return t


# ─── Init ─────────────────────────────────────────────────────────────────────

class TestInit:
    def test_stores_client(self, mock_client):
        f = OptionsFlowFetcher(client=mock_client)
        assert f._client is mock_client


# ─── fetch_and_persist ────────────────────────────────────────────────────────

class TestFetchAndPersist:
    def test_returns_int(self, fetcher):
        with patch("yfinance.Ticker") as MockTicker:
            MockTicker.return_value = _make_ticker_mock()
            result = fetcher.fetch_and_persist(["SPY"])
        assert isinstance(result, int)

    def test_empty_tickers_returns_zero(self, fetcher):
        result = fetcher.fetch_and_persist([])
        assert result == 0

    def test_calls_execute_on_valid_chain(self, mock_client):
        with patch("yfinance.Ticker") as MockTicker:
            MockTicker.return_value = _make_ticker_mock()
            OptionsFlowFetcher(client=mock_client).fetch_and_persist(["SPY"])
        assert mock_client.execute.called

    def test_no_crash_on_yfinance_error(self, fetcher):
        with patch("yfinance.Ticker", side_effect=RuntimeError("network")):
            result = fetcher.fetch_and_persist(["SPY"])
        assert result == 0

    def test_no_options_returns_zero(self, fetcher):
        with patch("yfinance.Ticker") as MockTicker:
            t = MagicMock()
            t.options = []
            MockTicker.return_value = t
            result = fetcher.fetch_and_persist(["SPY"])
        assert result == 0

    def test_aggregates_multiple_tickers(self, mock_client):
        with patch("yfinance.Ticker") as MockTicker:
            MockTicker.return_value = _make_ticker_mock()
            f = OptionsFlowFetcher(client=mock_client)
            result = f.fetch_and_persist(["SPY", "QQQ", "AAPL"])
        assert result == 3

    def test_chain_error_returns_zero(self, fetcher):
        with patch("yfinance.Ticker") as MockTicker:
            t = MagicMock()
            t.options = ["2026-06-20"]
            t.option_chain.side_effect = Exception("chain unavailable")
            t.info = {"regularMarketPrice": 500.0}
            MockTicker.return_value = t
            result = fetcher.fetch_and_persist(["SPY"])
        assert result == 0


# ─── get_latest ───────────────────────────────────────────────────────────────

class TestGetLatest:
    def test_returns_none_when_no_data(self, fetcher):
        result = fetcher.get_latest("SPY")
        assert result is None

    def test_returns_dict_with_data(self, mock_client):
        mock_client.query.return_value = [
            ("SPY", date.today(), 0.85, 100000, 120000, 500000, 600000, 0.03, 0.18, "yfinance_derived")
        ]
        f = OptionsFlowFetcher(client=mock_client)
        result = f.get_latest("SPY")
        assert result is not None
        assert result["put_call_ratio"] == 0.85
        assert result["ticker"] == "SPY"

    def test_returns_none_on_db_error(self, mock_client):
        mock_client.query.side_effect = Exception("DB")
        f = OptionsFlowFetcher(client=mock_client)
        assert f.get_latest("SPY") is None


# ─── get_history ──────────────────────────────────────────────────────────────

class TestGetHistory:
    def test_returns_dataframe(self, fetcher):
        df = fetcher.get_history("SPY")
        assert isinstance(df, pd.DataFrame)

    def test_returns_empty_on_db_error(self, mock_client):
        mock_client.query.side_effect = Exception("DB")
        f = OptionsFlowFetcher(client=mock_client)
        df = f.get_history("SPY")
        assert df.empty

    def test_has_expected_columns(self, fetcher):
        df = fetcher.get_history("SPY")
        assert set(df.columns) == {"ticker", "date", "put_call_ratio", "iv_skew_25d", "iv_atm", "source"}


# ─── _compute_metrics ─────────────────────────────────────────────────────────

class TestComputeMetrics:
    def _calls(self):
        return _make_chain_df([490, 500, 510], [0.18, 0.17, 0.18], [200, 500, 200], [1000, 2000, 1000])

    def _puts(self):
        return _make_chain_df([490, 500, 510], [0.20, 0.17, 0.16], [250, 600, 250], [1200, 2500, 1200])

    def test_returns_dict(self):
        m = _compute_metrics(self._calls(), self._puts(), spot=500.0)
        assert isinstance(m, dict)

    def test_put_call_ratio_positive(self):
        m = _compute_metrics(self._calls(), self._puts(), spot=500.0)
        assert m["put_call_ratio"] > 0

    def test_none_on_empty_dfs(self):
        result = _compute_metrics(pd.DataFrame(), pd.DataFrame(), spot=500.0)
        assert result is None

    def test_volumes_aggregated(self):
        m = _compute_metrics(self._calls(), self._puts(), spot=500.0)
        assert m["call_volume"] == 900    # 200+500+200
        assert m["put_volume"]  == 1100   # 250+600+250

    def test_oi_fallback_when_no_volume(self):
        calls = _make_chain_df([500], [0.17], [None], [2000])
        puts  = _make_chain_df([500], [0.17], [None], [3000])
        m = _compute_metrics(calls, puts, spot=500.0)
        # P/C OI = 3000/2000 = 1.5
        assert m is not None
        assert abs(m["put_call_ratio"] - 1.5) < 0.01


# ─── _compute_iv_atm ──────────────────────────────────────────────────────────

class TestComputeIvAtm:
    def test_returns_float_near_spot(self):
        calls = _make_chain_df([490, 500, 510], [0.20, 0.17, 0.19], [100, 500, 100], [500, 2000, 500])
        puts  = pd.DataFrame()
        iv = _compute_iv_atm(calls, puts, spot=500.0)
        assert iv == pytest.approx(0.17)

    def test_none_when_spot_is_none(self):
        calls = _make_chain_df([500], [0.17], [100], [1000])
        assert _compute_iv_atm(calls, pd.DataFrame(), spot=None) is None

    def test_none_on_empty_dfs(self):
        assert _compute_iv_atm(pd.DataFrame(), pd.DataFrame(), spot=500.0) is None


# ─── _compute_iv_skew ─────────────────────────────────────────────────────────

class TestComputeIvSkew:
    def test_put_skew_positive_when_puts_pricier(self):
        # OTM puts (~475) costano di più degli OTM calls (~525)
        calls = _make_chain_df([500, 525, 550], [0.17, 0.18, 0.19], [500, 100, 50], [2000, 500, 200])
        puts  = _make_chain_df([500, 475, 450], [0.17, 0.22, 0.25], [600, 150, 60], [2500, 600, 250])
        skew = _compute_iv_skew(calls, puts, spot=500.0)
        assert skew is not None
        assert skew > 0  # put skew positivo

    def test_none_when_no_otm_options(self):
        calls = _make_chain_df([500], [0.17], [500], [2000])
        puts  = _make_chain_df([500], [0.17], [600], [2500])
        skew = _compute_iv_skew(calls, puts, spot=500.0)
        assert skew is None


# ─── _safe_options ────────────────────────────────────────────────────────────

class TestSafeOptions:
    def test_returns_list(self):
        t = MagicMock()
        t.options = ("2026-06-20", "2026-09-19")
        assert _safe_options(t) == ["2026-06-20", "2026-09-19"]

    def test_empty_list_on_exception(self):
        t = MagicMock()
        t.options = property(lambda self: (_ for _ in ()).throw(RuntimeError()))
        assert _safe_options(t) == []

    def test_none_options_returns_empty(self):
        t = MagicMock()
        t.options = None
        assert _safe_options(t) == []


# ─── _sum_col ─────────────────────────────────────────────────────────────────

class TestSumCol:
    def test_sums_integers(self):
        df = pd.DataFrame({"volume": [100, 200, 300]})
        assert _sum_col(df, "volume") == 600

    def test_ignores_nans(self):
        df = pd.DataFrame({"volume": [100, None, 300]})
        assert _sum_col(df, "volume") == 400

    def test_missing_col_returns_none(self):
        df = pd.DataFrame({"other": [1, 2]})
        assert _sum_col(df, "volume") is None

    def test_empty_df_returns_none(self):
        assert _sum_col(pd.DataFrame(), "volume") is None


# ─── _f, _int_or_none ────────────────────────────────────────────────────────

class TestHelpers:
    def test_f_valid(self):
        assert _f(1.5) == 1.5

    def test_f_none(self):
        assert _f(None) is None

    def test_f_nan(self):
        assert _f(float("nan")) is None

    def test_int_or_none_valid(self):
        assert _int_or_none(3.7) == 3

    def test_int_or_none_none(self):
        assert _int_or_none(None) is None

    def test_int_or_none_invalid(self):
        assert _int_or_none("abc") is None
