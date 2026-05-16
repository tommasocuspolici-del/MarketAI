"""Tests for engine.market_data.kpi_computer — KpiComputer + helpers."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from engine.market_data.kpi_computer import (
    DeltaWindow,
    KpiComputer,
    MarketKpi,
    MarketSnapshot,
    _safe_float,
    build_unavailable_kpis,
    download_market_data,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_kpi_computer(
    ws_price: float | None = None,
    cached: MarketKpi | None = None,
    sanity_safe: bool = True,
) -> KpiComputer:
    override_store = MagicMock()
    override_store.resolve.side_effect = lambda kind, term, val: (val, False)

    sanity = MagicMock()
    sanity.check_price_data.return_value = []
    sanity.is_safe_to_store.return_value = sanity_safe

    return KpiComputer(
        override_store=override_store,
        sanity=sanity,
        get_ws_price_fn=lambda t: ws_price,
        lookup_cached_fn=lambda t: cached,
    )


def _make_multiindex_data(tickers=("^GSPC", "^VIX"), prices=(4500.0, 18.0)):
    arrays = [["Close", "Close", "Open", "Open"], [tickers[0], tickers[1], tickers[0], tickers[1]]]
    cols = pd.MultiIndex.from_arrays(arrays, names=["field", "ticker"])
    data = [
        [prices[0] - 10, prices[1] - 1, prices[0] - 12, prices[1] - 1.1],
        [prices[0], prices[1], prices[0] - 1, prices[1] - 0.5],
    ]
    return pd.DataFrame(data, columns=cols, index=pd.date_range("2024-01-01", periods=2))


# ─── _safe_float ─────────────────────────────────────────────────────────────

class TestSafeFloat:
    def test_scalar(self) -> None:
        assert _safe_float(3.14) == pytest.approx(3.14)

    def test_int(self) -> None:
        assert _safe_float(42) == pytest.approx(42.0)

    def test_numpy_scalar(self) -> None:
        assert _safe_float(np.float64(2.5)) == pytest.approx(2.5)

    def test_pandas_series(self) -> None:
        s = pd.Series([1.0, 2.0, 3.0])
        assert _safe_float(s) == pytest.approx(3.0)

    def test_pandas_series_with_nan(self) -> None:
        s = pd.Series([1.0, np.nan, 3.0])
        assert _safe_float(s) == pytest.approx(3.0)

    def test_empty_series_returns_nan(self) -> None:
        s = pd.Series([], dtype=float)
        result = _safe_float(s)
        assert np.isnan(result)

    def test_all_nan_series_returns_nan(self) -> None:
        s = pd.Series([np.nan, np.nan])
        result = _safe_float(s)
        assert np.isnan(result)


# ─── build_unavailable_kpis ──────────────────────────────────────────────────

class TestBuildUnavailableKpis:
    def test_returns_list_of_kpis(self) -> None:
        result = build_unavailable_kpis("no network")
        assert len(result) > 0
        assert all(isinstance(k, MarketKpi) for k in result)

    def test_all_have_error_set(self) -> None:
        result = build_unavailable_kpis("network down")
        assert all(k.error == "network down" for k in result)

    def test_value_is_none(self) -> None:
        result = build_unavailable_kpis("x")
        assert all(k.value is None for k in result)


# ─── MarketSnapshot ──────────────────────────────────────────────────────────

class TestMarketSnapshot:
    def test_empty_factory(self) -> None:
        snap = MarketSnapshot.empty("test")
        assert snap.is_unavailable is True
        assert snap.kpis == []

    def test_fetched_at_human_never(self) -> None:
        snap = MarketSnapshot()
        assert snap.fetched_at_human == "mai"

    def test_fetched_at_human_seconds(self) -> None:
        snap = MarketSnapshot(fetched_at=time.time() - 30)
        assert "s fa" in snap.fetched_at_human

    def test_fetched_at_human_minutes(self) -> None:
        snap = MarketSnapshot(fetched_at=time.time() - 600)
        assert "m fa" in snap.fetched_at_human

    def test_fetched_at_human_hours(self) -> None:
        snap = MarketSnapshot(fetched_at=time.time() - 7200)
        assert "h fa" in snap.fetched_at_human


# ─── MarketKpi & DeltaWindow dataclasses ─────────────────────────────────────

class TestDataclasses:
    def test_market_kpi_frozen(self) -> None:
        k = MarketKpi(term="X", yf_ticker="X", value=1.0, delta_pct=0.01,
                     currency="USD", format_spec=".2f")
        with pytest.raises((AttributeError, TypeError)):
            k.value = 2.0  # type: ignore[misc]

    def test_delta_window_defaults(self) -> None:
        dw = DeltaWindow(term="X", ticker="X", delta_1w=None, delta_1m=None, delta_ytd=None)
        assert dw.last_price is None
        assert dw.error == ""


# ─── KpiComputer.extract_kpi ─────────────────────────────────────────────────

class TestExtractKpiWebSocketPath:
    def test_ws_price_used_first(self) -> None:
        computer = _make_kpi_computer(ws_price=4520.5)
        data = _make_multiindex_data()
        result = computer.extract_kpi(
            data=data, term="S&P 500", yf_ticker="^GSPC",
            currency="USD", fmt=",.2f",
        )
        assert result.value == pytest.approx(4520.5)
        assert result.delta_pct is None


class TestExtractKpiDataFramePath:
    def test_basic_extract_from_multiindex(self) -> None:
        computer = _make_kpi_computer(ws_price=None)
        data = _make_multiindex_data()
        result = computer.extract_kpi(
            data=data, term="S&P 500", yf_ticker="^GSPC",
            currency="USD", fmt=",.2f",
        )
        assert result.value == pytest.approx(4500.0)
        assert result.delta_pct is not None

    def test_returns_kpi_on_missing_ticker(self) -> None:
        computer = _make_kpi_computer(ws_price=None)
        data = _make_multiindex_data()
        with patch.object(KpiComputer, "fetch_fast_info_fallback", return_value=(None, None)):
            result = computer.extract_kpi(
                data=data, term="Missing", yf_ticker="NONEXISTENT",
                currency="USD", fmt=",.2f",
            )
        assert result.value is None
        assert "silent_failure" in result.error

    def test_sanity_violation_falls_back_to_cache(self) -> None:
        cached = MarketKpi(term="S&P 500", yf_ticker="^GSPC", value=4400.0,
                          delta_pct=0.01, currency="USD", format_spec=",.2f")
        computer = _make_kpi_computer(ws_price=None, cached=cached, sanity_safe=False)
        data = _make_multiindex_data()
        result = computer.extract_kpi(
            data=data, term="S&P 500", yf_ticker="^GSPC",
            currency="USD", fmt=",.2f",
        )
        assert result.value == pytest.approx(4400.0)
        assert result.is_stale is True

    def test_empty_data_uses_fast_info_fallback(self) -> None:
        computer = _make_kpi_computer(ws_price=None)
        empty_data = pd.DataFrame()
        with patch.object(KpiComputer, "fetch_fast_info_fallback", return_value=(4505.0, 0.005)):
            result = computer.extract_kpi(
                data=empty_data, term="S&P 500", yf_ticker="^GSPC",
                currency="USD", fmt=",.2f",
            )
        assert result.value == pytest.approx(4505.0)
        assert result.delta_pct == pytest.approx(0.005)

    def test_empty_data_falls_back_to_cache_when_fast_info_fails(self) -> None:
        cached = MarketKpi(term="S&P 500", yf_ticker="^GSPC", value=4400.0,
                          delta_pct=0.01, currency="USD", format_spec=",.2f")
        computer = _make_kpi_computer(ws_price=None, cached=cached)
        empty_data = pd.DataFrame()
        with patch.object(KpiComputer, "fetch_fast_info_fallback", return_value=(None, None)):
            result = computer.extract_kpi(
                data=empty_data, term="S&P 500", yf_ticker="^GSPC",
                currency="USD", fmt=",.2f",
            )
        assert result.value == pytest.approx(4400.0)
        assert result.is_stale is True


# ─── KpiComputer.get_ticker_frame ────────────────────────────────────────────

class TestGetTickerFrame:
    def test_none_data(self) -> None:
        assert KpiComputer.get_ticker_frame(None, "X") is None

    def test_empty_data(self) -> None:
        assert KpiComputer.get_ticker_frame(pd.DataFrame(), "X") is None

    def test_multiindex_field_ticker_layout(self) -> None:
        data = _make_multiindex_data()
        result = KpiComputer.get_ticker_frame(data, "^GSPC")
        assert result is not None
        assert "Close" in result.columns

    def test_multiindex_ticker_not_present(self) -> None:
        data = _make_multiindex_data()
        result = KpiComputer.get_ticker_frame(data, "NOT_THERE")
        assert result is None

    def test_flat_columns_with_close(self) -> None:
        df = pd.DataFrame({"Close": [100.0, 101.0], "Open": [99.0, 100.5]})
        result = KpiComputer.get_ticker_frame(df, "ANY")
        assert result is df

    def test_flat_columns_without_close(self) -> None:
        df = pd.DataFrame({"foo": [100.0], "bar": [99.0]})
        result = KpiComputer.get_ticker_frame(df, "ANY")
        assert result is None

    def test_multiindex_ticker_field_layout(self) -> None:
        # MultiIndex with ticker on level 0, field on level 1
        arrays = [["^GSPC", "^GSPC"], ["Close", "Open"]]
        cols = pd.MultiIndex.from_arrays(arrays, names=["ticker", "field"])
        data = pd.DataFrame([[100.0, 99.0]], columns=cols, index=pd.date_range("2024-01-01", periods=1))
        result = KpiComputer.get_ticker_frame(data, "^GSPC")
        assert result is not None


# ─── KpiComputer.fetch_fast_info_fallback ────────────────────────────────────

class TestFetchFastInfoFallback:
    def test_returns_price_and_delta(self) -> None:
        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.fast_info = MagicMock(
                last_price=4500.0, previous_close=4475.0,
            )
            price, delta = KpiComputer.fetch_fast_info_fallback("^GSPC")
        assert price == pytest.approx(4500.0)
        assert delta == pytest.approx((4500.0 - 4475.0) / 4475.0)

    def test_returns_none_on_nan(self) -> None:
        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.fast_info = MagicMock(
                last_price=float("nan"), previous_close=4475.0,
            )
            price, delta = KpiComputer.fetch_fast_info_fallback("^GSPC")
        assert price is None
        assert delta is None

    def test_returns_none_when_price_missing(self) -> None:
        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.fast_info = MagicMock(
                last_price=None, previous_close=4475.0,
            )
            price, delta = KpiComputer.fetch_fast_info_fallback("^GSPC")
        assert price is None

    def test_returns_none_on_exception(self) -> None:
        with patch("yfinance.Ticker", side_effect=RuntimeError("API down")):
            price, delta = KpiComputer.fetch_fast_info_fallback("^GSPC")
        assert price is None
        assert delta is None

    def test_no_delta_when_prev_zero(self) -> None:
        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.fast_info = MagicMock(
                last_price=4500.0, previous_close=0,
            )
            price, delta = KpiComputer.fetch_fast_info_fallback("^GSPC")
        assert price == pytest.approx(4500.0)
        assert delta is None

    def test_no_delta_when_prev_none(self) -> None:
        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.fast_info = MagicMock(
                last_price=4500.0, previous_close=None,
            )
            price, delta = KpiComputer.fetch_fast_info_fallback("^GSPC")
        assert price == pytest.approx(4500.0)
        assert delta is None


# ─── download_market_data ────────────────────────────────────────────────────

class TestDownloadMarketData:
    def test_returns_none_on_yfinance_import_error(self, monkeypatch) -> None:
        import builtins
        real_import = builtins.__import__

        def _block_yf(name, *a, **k):
            if name == "yfinance":
                raise ImportError("not installed")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", _block_yf)
        result = download_market_data(["^GSPC"])
        assert result is None

    def test_returns_dataframe_when_success(self) -> None:
        mock_data = _make_multiindex_data()
        with patch("yfinance.download", return_value=mock_data):
            result = download_market_data(["^GSPC", "^VIX"])
        assert result is not None

    def test_returns_none_when_empty(self) -> None:
        with patch("yfinance.download", return_value=pd.DataFrame()):
            result = download_market_data(["^GSPC"])
        assert result is None

    def test_typeerror_triggers_retry_path(self) -> None:
        mock_data = _make_multiindex_data()
        call_count = [0]

        def _yf_download(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise TypeError("unexpected kwarg multi_level_index")
            return mock_data

        with patch("yfinance.download", side_effect=_yf_download):
            result = download_market_data(["^GSPC"])
        assert result is not None
        assert call_count[0] == 2  # retry happened

    def test_returns_none_on_oserror(self) -> None:
        with patch("yfinance.download", side_effect=OSError("network")):
            result = download_market_data(["^GSPC"])
        assert result is None

    def test_typeerror_then_oserror_returns_none(self) -> None:
        call_count = [0]

        def _yf_download(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise TypeError("kwarg error")
            raise OSError("retry also failed")

        with patch("yfinance.download", side_effect=_yf_download):
            result = download_market_data(["^GSPC"])
        assert result is None
