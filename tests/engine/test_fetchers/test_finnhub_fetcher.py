"""Tests for engine.market_data.fetchers.finnhub_fetcher."""
from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from engine.market_data.fetchers.finnhub_fetcher import FinnhubFetcher, NewsSentiment
from shared.constants import MIGRATIONS_DUCKDB_DIR
from shared.db.dual_writer import DualWriter
from shared.db.duckdb_client import DuckDBClient
from shared.db.duckdb_migrator import DuckDBMigrator
from shared.db.macro_repo import MacroRepository
from shared.db.prices_repo import PricesRepository
from shared.db.quality import QualityReportRepository
from shared.exceptions import ConfigurationError, FeatureDisabledError, FetchError
from shared.rate_limit_manager import RateLimitManager
from shared.types import TimeFrame

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def finnhub_deps(tmp_duckdb_path: Path, tmp_path: Path) -> dict[str, object]:
    client = DuckDBClient(path=tmp_duckdb_path)
    DuckDBMigrator(client=client, migrations_dir=MIGRATIONS_DUCKDB_DIR).apply_pending()

    rate_limits = tmp_path / "rate_limits.yaml"
    rate_limits.write_text(
        "finnhub:\n"
        "  requests_per_minute: 600\n"
        "  requests_per_day: unlimited\n"
        "  burst_size: 10\n",
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
        "api_key": "test_finnhub_key",
    }


def _candle_payload_ok(n: int = 10) -> dict[str, object]:
    """Stand-in for /stock/candle response."""
    base_ts = 1735689600  # 2025-01-01 00:00:00 UTC in epoch seconds
    return {
        "s": "ok",
        "t": [base_ts + i * 86400 for i in range(n)],
        "o": [100.0 + i for i in range(n)],
        "h": [101.0 + i for i in range(n)],
        "l": [99.0 + i for i in range(n)],
        "c": [100.5 + i for i in range(n)],
        "v": [1_000_000 + i * 100 for i in range(n)],
    }


# ═══════════════════════════════════════════════════════════════════════════
# Construction
# ═══════════════════════════════════════════════════════════════════════════
class TestConstruction:
    def test_missing_api_key_raises(
        self,
        finnhub_deps: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
        deps = {k: v for k, v in finnhub_deps.items() if k != "api_key"}
        with pytest.raises(ConfigurationError, match="FINNHUB_API_KEY"):
            FinnhubFetcher(**deps)  # type: ignore[arg-type]

    def test_api_key_from_env(
        self,
        finnhub_deps: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("FINNHUB_API_KEY", "env_finnhub_key_123")
        deps = {k: v for k, v in finnhub_deps.items() if k != "api_key"}
        fetcher = FinnhubFetcher(**deps)  # type: ignore[arg-type]
        assert fetcher._api_key == "env_finnhub_key_123"


# ═══════════════════════════════════════════════════════════════════════════
# Candle payload normalization
# ═══════════════════════════════════════════════════════════════════════════
class TestNormalizeCandlePayload:
    def test_canonical_columns_and_dtypes(self) -> None:
        df = FinnhubFetcher._normalize_candle_payload(_candle_payload_ok(10), "AAPL")
        assert len(df) == 10
        for col in ("ts", "open", "high", "low", "close", "volume", "adj_close"):
            assert col in df.columns
        assert df["ts"].dt.tz is not None
        assert df["volume"].dtype == "int64"

    def test_no_data_returns_empty(self) -> None:
        df = FinnhubFetcher._normalize_candle_payload({"s": "no_data"}, "X")
        assert df.empty

    def test_unexpected_status_raises(self) -> None:
        with pytest.raises(FetchError, match="status"):
            FinnhubFetcher._normalize_candle_payload({"s": "error"}, "X")


# ═══════════════════════════════════════════════════════════════════════════
# OHLCV pipeline
# ═══════════════════════════════════════════════════════════════════════════
class TestOhlcvPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline(self, finnhub_deps: dict[str, object]) -> None:
        fetcher = FinnhubFetcher(**finnhub_deps)  # type: ignore[arg-type]

        async def _fake_get(_url: str, _params: dict[str, object]) -> dict[str, object]:
            return _candle_payload_ok(20)

        with patch.object(fetcher, "_get_json", new=AsyncMock(side_effect=_fake_get)):
            outcome = await fetcher.fetch(
                ticker="AAPL", exchange="NASDAQ", timeframe=TimeFrame.D1
            )
        assert outcome.write_result.rows_written == 20

    @pytest.mark.asyncio
    async def test_unsupported_timeframe_raises(
        self, finnhub_deps: dict[str, object]
    ) -> None:
        fetcher = FinnhubFetcher(**finnhub_deps)  # type: ignore[arg-type]
        with pytest.raises(FetchError, match="unsupported timeframe"):
            await fetcher.fetch(ticker="X", exchange="Y", timeframe="4h")


# ═══════════════════════════════════════════════════════════════════════════
# News sentiment
# ═══════════════════════════════════════════════════════════════════════════
class TestNewsSentiment:
    @pytest.mark.asyncio
    async def test_sentiment_parsing(self, finnhub_deps: dict[str, object]) -> None:
        fetcher = FinnhubFetcher(**finnhub_deps)  # type: ignore[arg-type]
        sentiment_payload = {
            "sentiment": {"bullishPercent": 0.62, "bearishPercent": 0.18},
            "buzz": {"articlesInLastWeek": 47},
        }

        async def _fake_get(_url: str, _params: dict[str, object]) -> dict[str, object]:
            return sentiment_payload

        with patch.object(fetcher, "_get_json", new=AsyncMock(side_effect=_fake_get)):
            sentiment = await fetcher.fetch_news_sentiment("AAPL")

        assert sentiment is not None
        assert sentiment.bullish_pct == pytest.approx(0.62)
        assert sentiment.bearish_pct == pytest.approx(0.18)
        assert sentiment.buzz_articles == 47
        # composite_score = bullish - bearish
        assert sentiment.composite_score == pytest.approx(0.44)

    @pytest.mark.asyncio
    async def test_empty_sentiment_returns_none(
        self, finnhub_deps: dict[str, object]
    ) -> None:
        fetcher = FinnhubFetcher(**finnhub_deps)  # type: ignore[arg-type]

        async def _fake_get(_url: str, _params: dict[str, object]) -> dict[str, object]:
            return {}

        with patch.object(fetcher, "_get_json", new=AsyncMock(side_effect=_fake_get)):
            sentiment = await fetcher.fetch_news_sentiment("UNKNOWN")
        assert sentiment is None

    def test_news_sentiment_value_object(self) -> None:
        from datetime import UTC, datetime

        s = NewsSentiment(
            ticker="X",
            ts=datetime.now(UTC),
            bullish_pct=0.5,
            bearish_pct=0.3,
            buzz_articles=10,
        )
        assert s.composite_score == pytest.approx(0.2)


# ═══════════════════════════════════════════════════════════════════════════
# WebSocket — feature flag (Rule 29)
# ═══════════════════════════════════════════════════════════════════════════
class TestWebSocketGate:
    @pytest.mark.asyncio
    async def test_websocket_disabled_raises(
        self,
        finnhub_deps: dict[str, object],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        flags_file = tmp_path / "feature_flags.yaml"
        flags_file.write_text("realtime_websocket: false\n", encoding="utf-8")
        monkeypatch.setattr("shared.feature_flags.FEATURE_FLAGS_PATH", flags_file)
        from shared.feature_flags import reload_flags

        reload_flags()

        fetcher = FinnhubFetcher(**finnhub_deps)  # type: ignore[arg-type]
        with pytest.raises(FeatureDisabledError):
            await fetcher.stream_ticks("AAPL")
