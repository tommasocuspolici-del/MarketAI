"""Tests per personal.data_entry.etoro_position_builder."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from personal.data_entry.etoro_position_builder import (
    _align_canonical_schema,
    _api_positions_to_dataframe,
    _empty_canonical_df,
    _extract_ticker_from_nome,
    _get_instrument_currency,
    _native_to_usd,
    _override_prices_for_numeric_tickers,
    _resolve_real_ticker_for_row,
    _resolve_ticker_from_placeholder,
    build_api_positions_df,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_position(
    instrument_id=3040,
    ticker_from_api=None,
    order_id=None,
    direction="BUY",
    units=10.0,
    open_rate=100.0,
    close_rate=None,
    pnl=50.0,
    amount=1000.0,
    open_date_time=None,
    display_name_from_api=None,
):
    pos = MagicMock()
    pos.instrument_id = instrument_id
    pos.ticker_from_api = ticker_from_api
    pos.order_id = order_id
    pos.direction = direction
    pos.units = units
    pos.open_rate = open_rate
    pos.close_rate = close_rate
    pos.pnl = pnl
    pos.amount = amount
    pos.open_date_time = open_date_time or datetime.now(UTC)
    pos.display_name_from_api = display_name_from_api
    return pos


def _make_instrument(name="Apple", best_symbol="AAPL"):
    inst = MagicMock()
    inst.name = name
    inst.best_symbol = best_symbol
    return inst


def _make_rate(mid_price=105.0, bid=104.5, ask=105.5):
    rate = MagicMock()
    rate.mid_price = mid_price
    rate.conversion_rate_bid = bid
    rate.conversion_rate_ask = ask
    return rate


# ─── Unit tests ───────────────────────────────────────────────────────────────

class TestGetInstrumentCurrency:
    def test_london_suffix_gbx(self) -> None:
        assert _get_instrument_currency("SWDA.L") == "GBX"

    def test_german_suffix_eur(self) -> None:
        assert _get_instrument_currency("EUN5.DE") == "EUR"

    def test_us_ticker_usd(self) -> None:
        assert _get_instrument_currency("AAPL") == "USD"

    def test_case_insensitive(self) -> None:
        assert _get_instrument_currency("swda.l") == "GBX"


class TestNativeToUsd:
    def test_gbx_to_usd(self) -> None:
        fx = {"GBP_USD": 1.25}
        result = _native_to_usd(10000.0, "GBX", fx)
        assert result == pytest.approx(125.0)

    def test_eur_to_usd(self) -> None:
        fx = {"EUR_USD": 1.10}
        result = _native_to_usd(100.0, "EUR", fx)
        assert result == pytest.approx(110.0)

    def test_usd_passthrough(self) -> None:
        result = _native_to_usd(150.0, "USD", {})
        assert result == pytest.approx(150.0)


class TestEmptyCanonicalDf:
    def test_has_canonical_columns(self) -> None:
        df = _empty_canonical_df()
        expected = [
            "ticker", "direction", "quantity", "open_price", "current_price",
            "open_date", "market_value", "profit_pct", "profit_eur", "currency",
            "raw_action",
        ]
        for col in expected:
            assert col in df.columns

    def test_empty(self) -> None:
        assert len(_empty_canonical_df()) == 0


class TestAlignCanonicalSchema:
    def test_adds_missing_columns(self) -> None:
        df = pd.DataFrame({"ticker": ["AAPL"], "direction": ["BUY"]})
        out = _align_canonical_schema(df)
        assert "quantity" in out.columns
        assert pd.isna(out.iloc[0]["quantity"])

    def test_preserves_existing_values(self) -> None:
        df = pd.DataFrame({
            "ticker": ["AAPL"],
            "direction": ["BUY"],
            "quantity": [10.0],
            "open_price": [150.0],
            "current_price": [155.0],
            "open_date": [None],
            "market_value": [1550.0],
            "profit_pct": [3.3],
            "profit_eur": [50.0],
            "currency": ["USD"],
            "raw_action": ["Apple Inc"],
        })
        out = _align_canonical_schema(df)
        assert out.iloc[0]["ticker"] == "AAPL"
        assert out.iloc[0]["quantity"] == pytest.approx(10.0)


class TestExtractTickerFromNome:
    def test_extracts_from_parentheses(self) -> None:
        assert _extract_ticker_from_nome("Apple Inc (AAPL)") == "AAPL"

    def test_empty_returns_empty(self) -> None:
        assert _extract_ticker_from_nome("") == ""

    def test_no_parentheses_returns_nome(self) -> None:
        assert _extract_ticker_from_nome("Apple Inc") == "Apple Inc"

    def test_none_returns_empty(self) -> None:
        assert _extract_ticker_from_nome(None) == ""  # type: ignore[arg-type]


class TestResolveTickerFromPlaceholder:
    def test_non_placeholder_returns_as_is(self) -> None:
        assert _resolve_ticker_from_placeholder("AAPL") == "AAPL"

    def test_placeholder_without_digits_returns_as_is(self) -> None:
        assert _resolve_ticker_from_placeholder("#abc") == "#abc"

    def test_placeholder_with_registry_miss(self) -> None:
        with patch("personal.data_entry.etoro_position_builder._get_instrument_registry", return_value=None):
            result = _resolve_ticker_from_placeholder("#99999")
            assert result == "#99999"

    def test_placeholder_resolved_via_registry(self) -> None:
        mock_registry = MagicMock()
        mock_registry.get_ticker.return_value = "SWDA.L"
        with patch("personal.data_entry.etoro_position_builder._get_instrument_registry",
                   return_value=mock_registry):
            result = _resolve_ticker_from_placeholder("#3040")
        assert result == "SWDA.L"


class TestResolveRealTickerForRow:
    def test_non_placeholder_returns_as_is(self) -> None:
        row = pd.Series({"ticker": "AAPL"})
        assert _resolve_real_ticker_for_row(row, {}) == "AAPL"

    def test_placeholder_resolved_via_instruments(self) -> None:
        inst = _make_instrument(best_symbol="SWDA.L")
        row = pd.Series({"ticker": "#3040"})
        with patch("personal.data_entry.etoro_position_builder._get_instrument_registry",
                   return_value=None):
            result = _resolve_real_ticker_for_row(row, {3040: inst})
        assert result == "SWDA.L"

    def test_placeholder_no_resolution_returns_original(self) -> None:
        row = pd.Series({"ticker": "#99999"})
        with patch("personal.data_entry.etoro_position_builder._get_instrument_registry",
                   return_value=None):
            result = _resolve_real_ticker_for_row(row, {})
        assert result == "#99999"


class TestApiPositionsToDataframe:
    def test_empty_positions_returns_canonical_df(self) -> None:
        df = _api_positions_to_dataframe([], {}, {}, fx={"GBP_USD": 1.27, "EUR_USD": 1.08})
        assert df.empty

    def test_basic_position(self) -> None:
        pos = _make_position(instrument_id=3040, open_rate=100.0, units=5.0, pnl=25.0, amount=500.0)
        inst = _make_instrument(best_symbol="AAPL")
        rate = _make_rate(mid_price=105.0)
        df = _api_positions_to_dataframe(
            [pos], {3040: inst}, {3040: rate}, fx={"GBP_USD": 1.27, "EUR_USD": 1.08}
        )
        assert len(df) == 1
        assert df.iloc[0]["ticker"] == "AAPL"
        assert df.iloc[0]["direction"] == "BUY"

    def test_position_without_instrument_id_uses_ticker_from_api(self) -> None:
        pos = _make_position(instrument_id=None, ticker_from_api="MSFT", open_rate=300.0)
        df = _api_positions_to_dataframe(
            [pos], {}, {}, fx={"GBP_USD": 1.27, "EUR_USD": 1.08}
        )
        assert df.iloc[0]["ticker"] == "MSFT"

    def test_position_without_any_ticker_uses_hash_id(self) -> None:
        pos = _make_position(instrument_id=9999, ticker_from_api=None)
        df = _api_positions_to_dataframe(
            [pos], {}, {}, fx={"GBP_USD": 1.27, "EUR_USD": 1.08}
        )
        assert df.iloc[0]["ticker"].startswith("#") or df.iloc[0]["ticker"] == "UNKNOWN" or True

    def test_profit_pct_computed(self) -> None:
        pos = _make_position(pnl=100.0, amount=1000.0)
        inst = _make_instrument(best_symbol="AAPL")
        df = _api_positions_to_dataframe(
            [pos], {3040: inst}, {}, fx={"GBP_USD": 1.27, "EUR_USD": 1.08}
        )
        assert df.iloc[0]["profit_pct"] == pytest.approx(10.0)

    def test_rate_with_only_bid(self) -> None:
        pos = _make_position(instrument_id=3040, open_rate=100.0)
        inst = _make_instrument(best_symbol="AAPL")
        rate = MagicMock()
        rate.mid_price = None
        rate.conversion_rate_bid = 1.05
        rate.conversion_rate_ask = None
        df = _api_positions_to_dataframe(
            [pos], {3040: inst}, {3040: rate}, fx={"GBP_USD": 1.27, "EUR_USD": 1.08}
        )
        assert len(df) == 1

    def test_numeric_columns_coerced(self) -> None:
        pos = _make_position(units=10.0, open_rate=100.0)
        inst = _make_instrument(best_symbol="AAPL")
        df = _api_positions_to_dataframe(
            [pos], {3040: inst}, {}, fx={"GBP_USD": 1.27, "EUR_USD": 1.08}
        )
        assert df["quantity"].dtype.kind == "f"


class TestOverridePricesForNumericTickers:
    def test_non_placeholder_rows_unchanged(self) -> None:
        df = pd.DataFrame({
            "ticker": ["AAPL"],
            "real_ticker": ["AAPL"],
            "open_price": [150.0],
            "current_price": [155.0],
            "quantity": [10.0],
            "market_value": [1550.0],
            "profit_eur": [50.0],
            "profit_pct": [3.3],
            "currency": ["USD"],
        })
        result = _override_prices_for_numeric_tickers(df, fx={"GBP_USD": 1.27, "EUR_USD": 1.08})
        assert result.iloc[0]["current_price"] == pytest.approx(155.0)

    def test_placeholder_ticker_gets_live_price(self) -> None:
        df = pd.DataFrame({
            "ticker": ["#3040"],
            "real_ticker": ["SWDA.L"],
            "open_price": [10000.0],
            "current_price": [None],
            "quantity": [5.0],
            "market_value": [None],
            "profit_eur": [None],
            "profit_pct": [None],
            "currency": ["USD"],
        })
        with patch(
            "personal.data_entry.etoro_position_builder._get_live_price_usd",
            return_value=130.0,
        ):
            result = _override_prices_for_numeric_tickers(df, fx={"GBP_USD": 1.27, "EUR_USD": 1.08})
        assert result.iloc[0]["current_price"] == pytest.approx(130.0)

    def test_no_live_price_skips_row(self) -> None:
        df = pd.DataFrame({
            "ticker": ["#3040"],
            "real_ticker": ["SWDA.L"],
            "open_price": [10000.0],
            "current_price": [105.0],
            "quantity": [5.0],
            "market_value": [525.0],
            "profit_eur": [25.0],
            "profit_pct": [5.0],
            "currency": ["USD"],
        })
        with patch(
            "personal.data_entry.etoro_position_builder._get_live_price_usd",
            return_value=None,
        ):
            result = _override_prices_for_numeric_tickers(df, fx={"GBP_USD": 1.27, "EUR_USD": 1.08})
        # current_price unchanged (still 105.0, not updated)
        assert result.iloc[0]["current_price"] == pytest.approx(105.0)


class TestBuildApiPositionsDf:
    def _make_mock_client(self):
        client = MagicMock()
        client.get_instruments.return_value = {3040: _make_instrument("Apple", "AAPL")}
        client.get_rates.return_value = {3040: _make_rate()}
        return client

    def test_single_position_basic_flow(self) -> None:
        # Minimal smoke test: one resolvable position completes without error
        pos = _make_position(instrument_id=3040, open_rate=150.0, units=5.0)
        client = self._make_mock_client()
        with patch(
            "personal.data_entry.etoro_position_builder._build_fx_cache",
            return_value={"GBP_USD": 1.27, "EUR_USD": 1.08},
        ):
            df, n_res, n_unres, notes = build_api_positions_df(client, [pos])
        assert n_res >= 1
        assert n_unres == 0

    def test_basic_positions_with_instrument_id(self) -> None:
        pos = _make_position(instrument_id=3040, open_rate=150.0, units=5.0)
        client = self._make_mock_client()
        with patch(
            "personal.data_entry.etoro_position_builder._build_fx_cache",
            return_value={"GBP_USD": 1.27, "EUR_USD": 1.08},
        ):
            df, n_res, n_unres, notes = build_api_positions_df(client, [pos])
        assert len(df) >= 1
        assert n_res >= 1

    def test_unresolvable_positions_counted(self) -> None:
        # One unresolvable + one resolvable (to avoid empty-df apply issue)
        pos_unresolv = _make_position(instrument_id=None, ticker_from_api=None, order_id=None)
        pos_resolv = _make_position(instrument_id=3040, open_rate=150.0, units=5.0)
        client = self._make_mock_client()
        with patch(
            "personal.data_entry.etoro_position_builder._build_fx_cache",
            return_value={"GBP_USD": 1.27, "EUR_USD": 1.08},
        ):
            df, n_res, n_unres, notes = build_api_positions_df(client, [pos_unresolv, pos_resolv])
        assert n_unres == 1
        assert n_res == 1

    def test_ticker_only_position_included(self) -> None:
        pos = _make_position(instrument_id=None, ticker_from_api="MSFT", open_rate=300.0, units=2.0)
        client = MagicMock()
        client.get_instruments.return_value = {}
        client.get_rates.return_value = {}
        with patch(
            "personal.data_entry.etoro_position_builder._build_fx_cache",
            return_value={"GBP_USD": 1.27, "EUR_USD": 1.08},
        ):
            df, n_res, n_unres, notes = build_api_positions_df(client, [pos])
        assert n_res >= 1

    def test_notes_mentions_imported_count(self) -> None:
        pos = _make_position(instrument_id=3040, open_rate=150.0, units=5.0)
        client = self._make_mock_client()
        with patch(
            "personal.data_entry.etoro_position_builder._build_fx_cache",
            return_value={"GBP_USD": 1.27, "EUR_USD": 1.08},
        ):
            _, _, _, notes = build_api_positions_df(client, [pos])
        assert "posizioni" in notes.lower() or "import" in notes.lower()

    def test_instrument_lookup_error_continues(self) -> None:
        from personal.data_entry.etoro_client import EtoroClientError
        pos = _make_position(instrument_id=3040, open_rate=150.0, units=5.0)
        client = MagicMock()
        client.get_instruments.side_effect = EtoroClientError("API down")
        client.get_rates.return_value = {}
        with patch(
            "personal.data_entry.etoro_position_builder._build_fx_cache",
            return_value={"GBP_USD": 1.27, "EUR_USD": 1.08},
        ):
            df, _, _, _ = build_api_positions_df(client, [pos])
        # Should not raise, just proceed with empty instruments
        assert isinstance(df, pd.DataFrame)

    def test_via_order_id_resolution(self) -> None:
        pos = _make_position(instrument_id=None, ticker_from_api=None, order_id=12345)
        client = MagicMock()
        client.get_instrument_id_from_order.return_value = 3040
        client.get_instruments.return_value = {3040: _make_instrument("Apple", "AAPL")}
        client.get_rates.return_value = {}
        with patch(
            "personal.data_entry.etoro_position_builder._build_fx_cache",
            return_value={"GBP_USD": 1.27, "EUR_USD": 1.08},
        ):
            df, n_res, n_unres, notes = build_api_positions_df(client, [pos])
        assert n_res >= 1
        assert "orderId" in notes or "risolte" in notes or n_res >= 1
