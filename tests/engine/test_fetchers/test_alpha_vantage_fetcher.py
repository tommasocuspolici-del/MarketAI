"""Tests for engine.market_data.fetchers.alpha_vantage_fetcher."""
from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from engine.market_data.fetchers.alpha_vantage_fetcher import AlphaVantageFetcher
from shared.constants import MIGRATIONS_DUCKDB_DIR
from shared.db.dual_writer import DualWriter
from shared.db.duckdb_client import DuckDBClient
from shared.db.duckdb_migrator import DuckDBMigrator
from shared.db.macro_repo import MacroRepository
from shared.db.prices_repo import PricesRepository
from shared.db.quality import QualityReportRepository
from shared.exceptions import ConfigurationError, FetchError
from shared.rate_limit_manager import RateLimitManager
from shared.types import TimeFrame

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def av_deps(tmp_duckdb_path: Path, tmp_path: Path) -> dict[str, object]:
    client = DuckDBClient(path=tmp_duckdb_path)
    DuckDBMigrator(client=client, migrations_dir=MIGRATIONS_DUCKDB_DIR).apply_pending()

    rate_limits = tmp_path / "rate_limits.yaml"
    rate_limits.write_text(
        "alpha_vantage:\n"
        "  requests_per_minute: 600\n"  # rilassato per i test
        "  requests_per_day: unlimited\n"
        "  burst_size: 5\n",
        encoding="utf-8",
    )

    return {
        "rate_limiter": RateLimitManager(config_path=rate_limits),
        "dual_writer": DualWriter(
            prices_repo=PricesRepository(client=client),
            macro_repo=MacroRepository(client=client),
            cache_dir=tmp_path / "cache",
        ),
        "quality_repo": QualityReportRepository(client=client),
        "api_key": "test_av_key",
    }


def _av_daily_payload() -> dict[str, object]:
    """Stand-in for TIME_SERIES_DAILY_ADJUSTED response."""
    return {
        "Meta Data": {
            "1. Information": "Daily Time Series with Splits and Dividend Events",
            "2. Symbol": "AAPL",
        },
        "Time Series (Daily)": {
            "2025-01-03": {
                "1. open": "180.00",
                "2. high": "182.50",
                "3. low": "179.50",
                "4. close": "181.20",
                "5. adjusted close": "181.20",
                "6. volume": "55000000",
            },
            "2025-01-02": {
                "1. open": "178.00",
                "2. high": "180.00",
                "3. low": "177.50",
                "4. close": "179.50",
                "5. adjusted close": "179.50",
                "6. volume": "60000000",
            },
        },
    }


def _av_fx_payload() -> dict[str, object]:
    return {
        "Meta Data": {"1. Information": "FX Daily"},
        "Time Series FX (Daily)": {
            "2025-01-03": {
                "1. open": "1.0850",
                "2. high": "1.0900",
                "3. low": "1.0820",
                "4. close": "1.0880",
            },
            "2025-01-02": {
                "1. open": "1.0830",
                "2. high": "1.0870",
                "3. low": "1.0810",
                "4. close": "1.0850",
            },
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# Construction
# ═══════════════════════════════════════════════════════════════════════════
class TestConstruction:
    def test_missing_api_key_raises(
        self, av_deps: dict[str, object], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ALPHA_VANTAGE_KEY", raising=False)
        deps = {k: v for k, v in av_deps.items() if k != "api_key"}
        with pytest.raises(ConfigurationError, match="ALPHA_VANTAGE_KEY"):
            AlphaVantageFetcher(**deps)  # type: ignore[arg-type]

    def test_api_key_from_env(
        self, av_deps: dict[str, object], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHA_VANTAGE_KEY", "env_av_xxx")
        deps = {k: v for k, v in av_deps.items() if k != "api_key"}
        fetcher = AlphaVantageFetcher(**deps)  # type: ignore[arg-type]
        assert fetcher._api_key == "env_av_xxx"


# ═══════════════════════════════════════════════════════════════════════════
# Payload normalization
# ═══════════════════════════════════════════════════════════════════════════
class TestNormalizeOhlcvPayload:
    def test_daily_payload_decoded(self) -> None:
        df = AlphaVantageFetcher._normalize_ohlcv_payload(
            _av_daily_payload(), "AAPL", "1d"
        )
        assert len(df) == 2
        # Ordinato per ts crescente
        assert df["ts"].is_monotonic_increasing
        # Prima riga = 2025-01-02 (la più vecchia)
        assert df["close"].iloc[0] == pytest.approx(179.50)
        assert df["close"].iloc[1] == pytest.approx(181.20)

    def test_payload_with_no_timeseries_returns_empty(self) -> None:
        df = AlphaVantageFetcher._normalize_ohlcv_payload(
            {"Meta Data": {}}, "X", "1d"
        )
        assert df.empty

    def test_volume_int64(self) -> None:
        df = AlphaVantageFetcher._normalize_ohlcv_payload(
            _av_daily_payload(), "AAPL", "1d"
        )
        assert df["volume"].dtype == "int64"


# ═══════════════════════════════════════════════════════════════════════════
# Error detection (AV returns 200 OK with error JSON body)
# ═══════════════════════════════════════════════════════════════════════════
class TestPayloadErrorDetection:
    def test_error_message_raises(
        self, av_deps: dict[str, object]
    ) -> None:
        fetcher = AlphaVantageFetcher(**av_deps)  # type: ignore[arg-type]
        with pytest.raises(FetchError):
            fetcher._check_payload_for_errors(
                {"Error Message": "Invalid API call"}
            )

    def test_note_raises_rate_limit_error(
        self, av_deps: dict[str, object]
    ) -> None:
        fetcher = AlphaVantageFetcher(**av_deps)  # type: ignore[arg-type]
        with pytest.raises(FetchError, match="rate limited"):
            fetcher._check_payload_for_errors(
                {"Note": "Thank you for using Alpha Vantage! Our standard API call frequency is 5 calls per minute."}
            )

    def test_information_only_payload_raises(
        self, av_deps: dict[str, object]
    ) -> None:
        fetcher = AlphaVantageFetcher(**av_deps)  # type: ignore[arg-type]
        with pytest.raises(FetchError, match="info-only"):
            fetcher._check_payload_for_errors(
                {"Information": "premium endpoint"}
            )

    def test_legitimate_payload_passes(self, av_deps: dict[str, object]) -> None:
        fetcher = AlphaVantageFetcher(**av_deps)  # type: ignore[arg-type]
        # Non deve sollevare
        fetcher._check_payload_for_errors(_av_daily_payload())


# ═══════════════════════════════════════════════════════════════════════════
# OHLCV pipeline
# ═══════════════════════════════════════════════════════════════════════════
class TestOhlcvPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline(self, av_deps: dict[str, object]) -> None:
        fetcher = AlphaVantageFetcher(**av_deps)  # type: ignore[arg-type]

        async def _fake_get(_url: str, _params: dict[str, object]) -> dict[str, object]:
            return _av_daily_payload()

        with patch.object(fetcher, "_get_json", new=AsyncMock(side_effect=_fake_get)):
            outcome = await fetcher.fetch(
                ticker="AAPL", exchange="NASDAQ", timeframe=TimeFrame.D1
            )
        assert outcome.write_result.rows_written == 2

    @pytest.mark.asyncio
    async def test_unsupported_timeframe_raises(
        self, av_deps: dict[str, object]
    ) -> None:
        fetcher = AlphaVantageFetcher(**av_deps)  # type: ignore[arg-type]
        with pytest.raises(FetchError, match="unsupported timeframe"):
            await fetcher.fetch(ticker="X", exchange="Y", timeframe="4h")


# ═══════════════════════════════════════════════════════════════════════════
# FX
# ═══════════════════════════════════════════════════════════════════════════
class TestFx:
    @pytest.mark.asyncio
    async def test_fx_returns_macro_shape(
        self, av_deps: dict[str, object]
    ) -> None:
        fetcher = AlphaVantageFetcher(**av_deps)  # type: ignore[arg-type]

        async def _fake_get(_url: str, _params: dict[str, object]) -> dict[str, object]:
            return _av_fx_payload()

        with patch.object(fetcher, "_get_json", new=AsyncMock(side_effect=_fake_get)):
            df = await fetcher.fetch_fx("EUR", "USD")

        assert len(df) == 2
        assert "ts" in df.columns and "value" in df.columns
        assert df["ts"].dt.tz is not None
        # Sorted ascending
        assert df["ts"].is_monotonic_increasing

    @pytest.mark.asyncio
    async def test_fx_empty_response(self, av_deps: dict[str, object]) -> None:
        fetcher = AlphaVantageFetcher(**av_deps)  # type: ignore[arg-type]

        async def _fake_get(_url: str, _params: dict[str, object]) -> dict[str, object]:
            return {"Meta Data": {}}

        with patch.object(fetcher, "_get_json", new=AsyncMock(side_effect=_fake_get)):
            df = await fetcher.fetch_fx("EUR", "USD")
        assert df.empty
