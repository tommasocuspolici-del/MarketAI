"""Tests for engine.market_data.fetchers.coingecko_fetcher."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import httpx
import pandas as pd
import pytest

from engine.market_data.fetchers.coingecko_fetcher import CoinGeckoFetcher, TOP_CRYPTO_IDS
from shared.exceptions import FetchError


def _mock_client() -> MagicMock:
    return MagicMock()


def _make_fetcher() -> CoinGeckoFetcher:
    with patch("httpx.Client"):
        return CoinGeckoFetcher(client=_mock_client())


def _coin_payload(n: int = 2) -> list[dict]:
    return [
        {
            "id": f"coin{i}", "symbol": f"C{i}", "name": f"Coin {i}",
            "market_cap_rank": i + 1,
            "current_price": 100.0 * (i + 1),
            "market_cap": 1_000_000 * (i + 1),
            "total_volume": 50_000 * (i + 1),
            "price_change_percentage_24h": 2.5,
        }
        for i in range(n)
    ]


# ── Constructor ───────────────────────────────────────────────────────────────

class TestInit:
    def test_top_crypto_ids_not_empty(self) -> None:
        assert len(TOP_CRYPTO_IDS) == 20

    def test_fetcher_created(self) -> None:
        fetcher = _make_fetcher()
        assert fetcher is not None


# ── fetch_top_prices() ────────────────────────────────────────────────────────

class TestFetchTopPrices:
    def test_success_returns_dataframe(self) -> None:
        fetcher = _make_fetcher()
        mock_resp = MagicMock()
        mock_resp.json.return_value = _coin_payload(3)
        mock_resp.raise_for_status.return_value = None
        fetcher._http.get.return_value = mock_resp

        with patch("time.sleep"):
            df = fetcher.fetch_top_prices(top_n=3)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3
        assert "ticker" in df.columns
        assert "price_usd" in df.columns

    def test_rate_limit_429_raises_fetch_error(self) -> None:
        fetcher = _make_fetcher()
        exc = httpx.HTTPStatusError("429", request=MagicMock(), response=MagicMock())
        exc.response.status_code = 429
        fetcher._http.get.side_effect = exc

        with patch("time.sleep"), pytest.raises(FetchError, match="Rate limit"):
            fetcher.fetch_top_prices()

    def test_http_error_non_429_raises_fetch_error(self) -> None:
        fetcher = _make_fetcher()
        exc = httpx.HTTPStatusError("503", request=MagicMock(), response=MagicMock())
        exc.response.status_code = 503
        fetcher._http.get.side_effect = exc

        with patch("time.sleep"), pytest.raises(FetchError, match="HTTP 503"):
            fetcher.fetch_top_prices()

    def test_generic_exception_raises_fetch_error(self) -> None:
        fetcher = _make_fetcher()
        fetcher._http.get.side_effect = OSError("timeout")

        with patch("time.sleep"), pytest.raises(FetchError):
            fetcher.fetch_top_prices()

    def test_empty_response_returns_empty_dataframe(self) -> None:
        fetcher = _make_fetcher()
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status.return_value = None
        fetcher._http.get.return_value = mock_resp

        with patch("time.sleep"):
            df = fetcher.fetch_top_prices()

        assert df.empty

    def test_persist_prices_called(self) -> None:
        fetcher = _make_fetcher()
        mock_resp = MagicMock()
        mock_resp.json.return_value = _coin_payload(2)
        mock_resp.raise_for_status.return_value = None
        fetcher._http.get.return_value = mock_resp

        with patch("time.sleep"), patch.object(fetcher, "_persist_prices") as mock_persist:
            fetcher.fetch_top_prices()
        mock_persist.assert_called_once()


# ── fetch_global_dominance() ──────────────────────────────────────────────────

class TestFetchGlobalDominance:
    def test_success_returns_dataframe(self) -> None:
        fetcher = _make_fetcher()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {
                "market_cap_percentage": {"btc": 48.5, "eth": 17.2},
                "total_market_cap": {"usd": 2.5e12},
                "total_volume": {"usd": 1e11},
                "active_cryptocurrencies": 15000,
            }
        }
        mock_resp.raise_for_status.return_value = None
        fetcher._http.get.return_value = mock_resp

        with patch("time.sleep"), patch.object(fetcher, "_persist_dominance"):
            df = fetcher.fetch_global_dominance()

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 5
        metrics = df["metric"].tolist()
        assert "btc_dominance" in metrics

    def test_http_error_raises_fetch_error(self) -> None:
        fetcher = _make_fetcher()
        fetcher._http.get.side_effect = OSError("network error")

        with patch("time.sleep"), pytest.raises(FetchError):
            fetcher.fetch_global_dominance()


# ── fetch_fear_greed_index() ──────────────────────────────────────────────────

class TestFetchFearGreedIndex:
    def test_success_returns_dict(self) -> None:
        fetcher = _make_fetcher()
        payload = {
            "data": [{
                "value": "75",
                "value_classification": "Greed",
                "timestamp": "1700000000",
            }]
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = payload
        mock_resp.raise_for_status.return_value = None

        with patch("time.sleep"), patch("httpx.get", return_value=mock_resp):
            result = fetcher.fetch_fear_greed_index()

        assert result is not None
        assert result["value"] == 75
        assert result["classification"] == "Greed"

    def test_empty_data_returns_none(self) -> None:
        fetcher = _make_fetcher()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status.return_value = None

        with patch("time.sleep"), patch("httpx.get", return_value=mock_resp):
            result = fetcher.fetch_fear_greed_index()

        assert result is None

    def test_exception_returns_none(self) -> None:
        fetcher = _make_fetcher()
        with patch("time.sleep"), patch("httpx.get", side_effect=OSError("timeout")):
            result = fetcher.fetch_fear_greed_index()
        assert result is None


# ── _persist_prices() ────────────────────────────────────────────────────────

class TestPersistPrices:
    def test_empty_df_skips(self) -> None:
        fetcher = _make_fetcher()
        fetcher._persist_prices(pd.DataFrame())
        fetcher._client.execute.assert_not_called()

    def test_rows_inserted(self) -> None:
        fetcher = _make_fetcher()
        df = pd.DataFrame([{
            "ticker": "BTC-USD", "price_usd": 50000.0, "volume_24h": 1e10,
        }])
        fetcher._persist_prices(df)
        fetcher._client.execute.assert_called()

    def test_none_price_skipped(self) -> None:
        fetcher = _make_fetcher()
        df = pd.DataFrame([{"ticker": "BTC-USD", "price_usd": None, "volume_24h": None}])
        fetcher._persist_prices(df)
        fetcher._client.execute.assert_not_called()

    def test_db_error_logged_not_raised(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.execute.side_effect = Exception("DB error")
        df = pd.DataFrame([{"ticker": "BTC-USD", "price_usd": 100.0, "volume_24h": 1000.0}])
        fetcher._persist_prices(df)  # should not raise


# ── _persist_dominance() ──────────────────────────────────────────────────────

class TestPersistDominance:
    def test_empty_df_skips(self) -> None:
        fetcher = _make_fetcher()
        fetcher._persist_dominance(pd.DataFrame())
        fetcher._client.execute.assert_not_called()

    def test_rows_inserted(self) -> None:
        fetcher = _make_fetcher()
        now = datetime.now(UTC)
        df = pd.DataFrame([{"metric": "btc_dominance", "value": 48.5, "fetched_at": now}])
        fetcher._persist_dominance(df)
        fetcher._client.execute.assert_called()

    def test_none_value_skipped(self) -> None:
        fetcher = _make_fetcher()
        now = datetime.now(UTC)
        df = pd.DataFrame([{"metric": "btc_dominance", "value": None, "fetched_at": now}])
        fetcher._persist_dominance(df)
        fetcher._client.execute.assert_not_called()

    def test_db_error_logged_not_raised(self) -> None:
        fetcher = _make_fetcher()
        fetcher._client.execute.side_effect = Exception("DB error")
        now = datetime.now(UTC)
        df = pd.DataFrame([{"metric": "btc_dominance", "value": 48.5, "fetched_at": now}])
        fetcher._persist_dominance(df)  # should not raise
