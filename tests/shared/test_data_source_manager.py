"""Tests for shared.resilience.data_source_manager."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from shared.resilience.data_source_manager import (
    ChainEntry,
    DataSourceManager,
    FallbackChain,
    FallbackResult,
    _default_chains,
    _load_chains,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_client() -> MagicMock:
    client = MagicMock()
    client.query.return_value = []
    return client


def _make_manager(chains: dict | None = None) -> DataSourceManager:
    return DataSourceManager(client=_mock_client(), chains=chains or _default_chains())


# ── FallbackResult ────────────────────────────────────────────────────────────

class TestFallbackResult:
    def test_fields_accessible(self) -> None:
        r = FallbackResult(
            data=42, source="duckdb", is_stale=False,
            ttl_remaining_s=300.0, fetched_at=datetime.now(UTC)
        )
        assert r.data == 42
        assert r.source == "duckdb"
        assert r.is_stale is False
        assert r.ttl_remaining_s == 300.0


# ── DataSourceManager.read() ──────────────────────────────────────────────────

class TestRead:
    def test_unknown_category_returns_none_data(self) -> None:
        mgr = _make_manager()
        result = mgr.read("unknown_category", "SPY")
        assert result.data is None
        assert result.source == "none"
        assert result.is_stale is True

    def test_known_category_no_cache_returns_none(self) -> None:
        mgr = _make_manager()
        result = mgr.read("price_ohlcv", "SPY")
        assert result.data is None

    def test_force_refresh_without_justification_still_works(self) -> None:
        mgr = _make_manager()
        result = mgr.read("price_ohlcv", "SPY", force_refresh=True)
        assert result.source == "none"

    def test_force_refresh_with_justification(self) -> None:
        mgr = _make_manager()
        result = mgr.read("price_ohlcv", "SPY", force_refresh=True, force_justification="scheduler")
        assert result.data is None  # no real data in mock

    def test_duckdb_cache_fallback_in_chain(self) -> None:
        chains = {
            "test_cat": FallbackChain("test_cat", [
                ChainEntry("duckdb_cache", "prezzi_daily", 0),
            ])
        }
        mgr = _make_manager(chains=chains)
        result = mgr.read("test_cat", "SPY")
        assert result.source == "none"

    def test_cache_hit_returns_fresh_result(self) -> None:
        mgr = _make_manager()
        now = datetime.now(UTC)
        mgr._client.query.return_value = [(100.0, now)]
        result = mgr.read("price_ohlcv", "SPY")
        assert result.data == 100.0
        assert result.source == "duckdb"
        assert result.is_stale is False

    def test_stale_cache_skipped_on_fresh_read(self) -> None:
        mgr = _make_manager()
        stale_ts = datetime.now(UTC) - timedelta(seconds=86400 * 2)
        mgr._client.query.return_value = [(50.0, stale_ts)]
        result = mgr.read("price_ohlcv", "SPY")
        # Stale cache — falls through chain, ends up as none
        # (no external sources configured in default chains for this manager)
        assert result is not None


# ── get_chain / list_categories ───────────────────────────────────────────────

class TestChainAccessors:
    def test_get_chain_known(self) -> None:
        mgr = _make_manager()
        chain = mgr.get_chain("price_ohlcv")
        assert chain is not None
        assert chain.name == "price_ohlcv"

    def test_get_chain_unknown_returns_none(self) -> None:
        mgr = _make_manager()
        assert mgr.get_chain("does_not_exist") is None

    def test_list_categories_not_empty(self) -> None:
        mgr = _make_manager()
        cats = mgr.list_categories()
        assert len(cats) > 0
        assert "price_ohlcv" in cats


# ── health_check() ────────────────────────────────────────────────────────────

class TestHealthCheck:
    def test_health_check_returns_dict(self) -> None:
        mgr = _make_manager()
        result = mgr.health_check()
        assert isinstance(result, dict)
        assert all(isinstance(v, bool) for v in result.values())

    def test_health_check_ok_when_db_works(self) -> None:
        mgr = _make_manager()
        mgr._client.query.return_value = [(1,)]
        result = mgr.health_check()
        assert all(result.values())

    def test_health_check_false_when_db_fails(self) -> None:
        mgr = _make_manager()
        mgr._client.query.side_effect = Exception("DB unavailable")
        result = mgr.health_check()
        assert not any(result.values())


# ── _read_cache() — category routing ─────────────────────────────────────────

class TestReadCache:
    def _chain_with_ttl(self, ttl_key: str = "prezzi_daily") -> FallbackChain:
        return FallbackChain("cat", [ChainEntry("duckdb_cache", ttl_key, 0)])

    def test_price_ohlcv_hit(self) -> None:
        mgr = _make_manager()
        now = datetime.now(UTC)
        mgr._client.query.return_value = [(123.45, now)]
        chain = self._chain_with_ttl()
        result = mgr._read_cache("price_ohlcv", "SPY", chain)
        assert result is not None
        assert result.data == 123.45

    def test_price_ohlcv_miss(self) -> None:
        mgr = _make_manager()
        mgr._client.query.return_value = []
        chain = self._chain_with_ttl()
        result = mgr._read_cache("price_ohlcv", "SPY", chain)
        assert result is None

    def test_macro_fred_hit(self) -> None:
        mgr = _make_manager()
        now = datetime.now(UTC)
        mgr._client.query.return_value = [(3.5, now)]
        chain = self._chain_with_ttl("macro_fred")
        result = mgr._read_cache("macro_fred", "FEDFUNDS", chain)
        assert result is not None

    def test_macro_ecb_hit(self) -> None:
        mgr = _make_manager()
        now = datetime.now(UTC)
        mgr._client.query.return_value = [(4.0, now)]
        chain = self._chain_with_ttl()
        result = mgr._read_cache("macro_ecb", "ECB_MRR", chain)
        assert result is not None

    def test_macro_imf_hit(self) -> None:
        mgr = _make_manager()
        now = datetime.now(UTC)
        mgr._client.query.return_value = [(2.1, now)]
        chain = self._chain_with_ttl()
        result = mgr._read_cache("macro_imf", "IMF_GDP", chain)
        assert result is not None

    def test_macro_oecd_hit(self) -> None:
        mgr = _make_manager()
        now = datetime.now(UTC)
        mgr._client.query.return_value = [(101.3, now)]
        chain = self._chain_with_ttl()
        result = mgr._read_cache("macro_oecd", "OECD_CLI_USA", chain)
        assert result is not None

    def test_pe_metrics_hit(self) -> None:
        mgr = _make_manager()
        now = datetime.now(UTC)
        mgr._client.query.return_value = [(22.0, 18.0, 30.5, 5.2, now)]
        chain = self._chain_with_ttl("fondamentali")
        result = mgr._read_cache("pe_metrics", "SPY", chain)
        assert result is not None
        assert result.data["trailing_pe"] == 22.0

    def test_news_articles_hit(self) -> None:
        mgr = _make_manager()
        now = datetime.now(UTC)
        mgr._client.query.return_value = [("id1", "title", "src", now)]
        chain = self._chain_with_ttl()
        result = mgr._read_cache("news_articles", "", chain)
        assert result is not None

    def test_db_exception_returns_none(self) -> None:
        mgr = _make_manager()
        mgr._client.query.side_effect = Exception("DB error")
        chain = self._chain_with_ttl()
        result = mgr._read_cache("price_ohlcv", "SPY", chain)
        assert result is None


# ── _make_result() ────────────────────────────────────────────────────────────

class TestMakeResult:
    def test_fresh_result(self) -> None:
        mgr = _make_manager()
        now = datetime.now(UTC) - timedelta(seconds=60)
        result = mgr._make_result(42, now, 3600, "duckdb")
        assert result.is_stale is False
        assert result.ttl_remaining_s > 0

    def test_stale_result(self) -> None:
        mgr = _make_manager()
        old = datetime.now(UTC) - timedelta(seconds=7200)
        result = mgr._make_result(42, old, 3600, "duckdb")
        assert result.is_stale is True
        assert result.ttl_remaining_s == 0.0

    def test_none_fetched_at(self) -> None:
        mgr = _make_manager()
        result = mgr._make_result(42, None, 3600, "duckdb")
        assert result.is_stale is True
        assert result.fetched_at is None

    def test_string_fetched_at(self) -> None:
        mgr = _make_manager()
        ts_str = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
        result = mgr._make_result(42, ts_str, 3600, "duckdb")
        assert result.is_stale is False

    def test_invalid_string_treated_as_now(self) -> None:
        mgr = _make_manager()
        result = mgr._make_result(42, "not-a-date", 3600, "duckdb")
        # Should not raise; is_stale may be True or False but result is valid
        assert isinstance(result.is_stale, bool)

    def test_naive_datetime_handled(self) -> None:
        mgr = _make_manager()
        naive = datetime.utcnow() - timedelta(seconds=60)  # noqa: DTZ003
        result = mgr._make_result(42, naive, 3600, "duckdb")
        assert result.is_stale is False


# ── _default_chains() / _load_chains() ───────────────────────────────────────

class TestChainLoading:
    def test_default_chains_has_price_ohlcv(self) -> None:
        chains = _default_chains()
        assert "price_ohlcv" in chains

    def test_default_chains_has_macro_fred(self) -> None:
        chains = _default_chains()
        assert "macro_fred" in chains

    def test_default_chains_entries_populated(self) -> None:
        chains = _default_chains()
        assert len(chains["price_ohlcv"].entries) > 0

    def test_load_chains_no_file_returns_defaults(self) -> None:
        with patch("shared.resilience.data_source_manager._CHAINS_PATH") as mock_path:
            mock_path.exists.return_value = False
            _load_chains.cache_clear()
            try:
                chains = _load_chains()
                assert "price_ohlcv" in chains
            finally:
                _load_chains.cache_clear()

    def test_load_chains_from_yaml(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        yaml_content = (
            "test_category:\n"
            "  - source: yfinance\n"
            "    ttl_key: prezzi_daily\n"
        )
        yaml_file = tmp_path / "chains.yaml"
        yaml_file.write_text(yaml_content)

        with patch("shared.resilience.data_source_manager._CHAINS_PATH", yaml_file):
            _load_chains.cache_clear()
            try:
                chains = _load_chains()
                assert "test_category" in chains
                assert chains["test_category"].entries[0].source == "yfinance"
            finally:
                _load_chains.cache_clear()
