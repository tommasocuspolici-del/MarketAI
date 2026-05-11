"""Tests for BaseFetcher v6 — Rule 12 pipeline orchestrator.

Uses a synthetic concrete subclass that returns canned DataFrames so we
can verify the full pipeline (rate limit → fetch → clean → validate
→ duckdb_write → cache → quality persist) without touching the network.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pytest

from engine.market_data.fetchers import (
    BaseMacroFetcher,
    BaseOhlcvFetcher,
    FetchOutcome,
)
from shared.constants import MIGRATIONS_DUCKDB_DIR
from shared.db.dual_writer import DualWriter
from shared.db.duckdb_client import DuckDBClient
from shared.db.duckdb_migrator import DuckDBMigrator
from shared.db.macro_repo import MacroRepository
from shared.db.prices_repo import PricesRepository
from shared.db.quality import QualityReportRepository
from shared.error_budget import error_budget
from shared.exceptions import FetchError
from shared.rate_limit_manager import RateLimitManager
from shared.types import TimeFrame

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════════
# Test fixtures: shared infra wired to ephemeral DuckDB
# ═══════════════════════════════════════════════════════════════════════════
@pytest.fixture
def configured_fetcher_deps(tmp_duckdb_path: Path, tmp_path: Path) -> dict[str, object]:
    """Provide all dependencies BaseFetcher needs, wired to a fresh DuckDB."""
    client = DuckDBClient(path=tmp_duckdb_path)
    DuckDBMigrator(client=client, migrations_dir=MIGRATIONS_DUCKDB_DIR).apply_pending()

    rate_limits_file = tmp_path / "rate_limits.yaml"
    rate_limits_file.write_text(
        "test_source:\n"
        "  requests_per_minute: 600\n"
        "  requests_per_day: unlimited\n"
        "  burst_size: 10\n",
        encoding="utf-8",
    )

    return {
        "rate_limiter": RateLimitManager(config_path=rate_limits_file),
        "dual_writer": DualWriter(
            prices_repo=PricesRepository(client=client),
            macro_repo=MacroRepository(client=client),
            cache_dir=tmp_path / "cache",
            cache_size_mb=64,
        ),
        "quality_repo": QualityReportRepository(client=client),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Mock fetchers (subclasses for testing only)
# ═══════════════════════════════════════════════════════════════════════════
class _StubOhlcvFetcher(BaseOhlcvFetcher):
    """Returns a canned OHLCV DataFrame, no network."""

    def __init__(self, df: pd.DataFrame, **deps: object) -> None:
        super().__init__(source="test_source", **deps)  # type: ignore[arg-type]
        self._df = df
        self.fetch_call_count: int = 0

    async def _fetch_raw_ohlcv(
        self,
        ticker: str,
        exchange: str,
        timeframe: TimeFrame,
        start: datetime | None,
        end: datetime | None,
    ) -> pd.DataFrame:
        self.fetch_call_count += 1
        return self._df.copy()


class _StubMacroFetcher(BaseMacroFetcher):
    def __init__(self, df: pd.DataFrame, **deps: object) -> None:
        super().__init__(source="test_source", **deps)  # type: ignore[arg-type]
        self._df = df
        self.fetch_call_count: int = 0

    async def _fetch_raw_macro(
        self,
        series_id: str,
        start: datetime | None,
        end: datetime | None,
    ) -> pd.DataFrame:
        self.fetch_call_count += 1
        return self._df.copy()


class _FailingOhlcvFetcher(BaseOhlcvFetcher):
    """Raises on every fetch — used to test error handling."""

    def __init__(self, **deps: object) -> None:
        super().__init__(source="test_source", **deps)  # type: ignore[arg-type]

    async def _fetch_raw_ohlcv(
        self,
        ticker: str,
        exchange: str,
        timeframe: TimeFrame,
        start: datetime | None,
        end: datetime | None,
    ) -> pd.DataFrame:
        raise RuntimeError("upstream API unavailable")


# ═══════════════════════════════════════════════════════════════════════════
# Helpers — sample DataFrames
# ═══════════════════════════════════════════════════════════════════════════
def _ohlcv_df(n: int = 50) -> pd.DataFrame:
    rng = np.random.default_rng(seed=99)
    ts = pd.date_range(start="2025-01-01", periods=n, freq="D", tz="UTC")
    log_ret = rng.normal(0.0005, 0.01, size=n)
    close = 100.0 * np.exp(np.cumsum(log_ret))
    return pd.DataFrame(
        {
            "ts": ts,
            "open": close * 0.999,
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": rng.integers(900_000, 1_100_000, size=n),
        }
    )


def _macro_df(n: int = 24) -> pd.DataFrame:
    ts = pd.date_range(start="2023-01-01", periods=n, freq="MS", tz="UTC")
    return pd.DataFrame({"ts": ts, "value": [3.0 + 0.05 * i for i in range(n)]})


# ═══════════════════════════════════════════════════════════════════════════
# OHLCV pipeline tests
# ═══════════════════════════════════════════════════════════════════════════
class TestOhlcvPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline_returns_outcome(
        self, configured_fetcher_deps: dict[str, object]
    ) -> None:
        df = _ohlcv_df(50)
        fetcher = _StubOhlcvFetcher(df=df, **configured_fetcher_deps)

        outcome = await fetcher.fetch(
            ticker="AAPL", exchange="NASDAQ", timeframe=TimeFrame.D1
        )

        assert isinstance(outcome, FetchOutcome)
        assert outcome.write_result.rows_written == 50
        assert outcome.report.series_id == "AAPL"
        assert outcome.report.series_kind == "prices"
        # Pipeline ha invocato _fetch_raw_ohlcv una volta
        assert fetcher.fetch_call_count == 1

    @pytest.mark.asyncio
    async def test_pipeline_persists_quality_report(
        self, configured_fetcher_deps: dict[str, object]
    ) -> None:
        df = _ohlcv_df(30)
        fetcher = _StubOhlcvFetcher(df=df, **configured_fetcher_deps)
        await fetcher.fetch(ticker="MSFT", exchange="NASDAQ", timeframe="1d")

        # Verifica persistenza: il quality_repo iniettato deve aver registrato il report
        repo = configured_fetcher_deps["quality_repo"]
        latest = repo.read_latest("MSFT")  # type: ignore[attr-defined]
        assert latest is not None
        assert latest.series_kind == "prices"

    @pytest.mark.asyncio
    async def test_pipeline_writes_to_duckdb_and_cache(
        self, configured_fetcher_deps: dict[str, object]
    ) -> None:
        df = _ohlcv_df(40)
        fetcher = _StubOhlcvFetcher(df=df, **configured_fetcher_deps)
        outcome = await fetcher.fetch(ticker="GOOG", exchange="NASDAQ", timeframe="1d")

        # Cache popolata
        dw = configured_fetcher_deps["dual_writer"]
        cached = dw.read_cached_prices("GOOG", "NASDAQ", "1d")  # type: ignore[attr-defined]
        assert cached is not None
        assert outcome.write_result.cached is True

    @pytest.mark.asyncio
    async def test_failing_fetch_raises_fetch_error(
        self, configured_fetcher_deps: dict[str, object]
    ) -> None:
        fetcher = _FailingOhlcvFetcher(**configured_fetcher_deps)

        # Reset error budget per asserzione mirata sotto
        error_budget.reset()

        with pytest.raises(FetchError):
            await fetcher.fetch(ticker="X", exchange="Y", timeframe="1d")

        # Error budget ha registrato il fallimento
        status = error_budget.status()
        assert status.error_events >= 1


# ═══════════════════════════════════════════════════════════════════════════
# Macro pipeline tests
# ═══════════════════════════════════════════════════════════════════════════
class TestMacroPipeline:
    @pytest.mark.asyncio
    async def test_macro_pipeline_full_run(
        self, configured_fetcher_deps: dict[str, object]
    ) -> None:
        df = _macro_df(24)
        fetcher = _StubMacroFetcher(df=df, **configured_fetcher_deps)

        outcome = await fetcher.fetch(
            series_id="UNRATE", unit="Percent", frequency="M"
        )
        assert outcome.write_result.rows_written == 24
        assert outcome.report.series_kind == "macro"

    @pytest.mark.asyncio
    async def test_macro_pipeline_persists_report(
        self, configured_fetcher_deps: dict[str, object]
    ) -> None:
        fetcher = _StubMacroFetcher(df=_macro_df(12), **configured_fetcher_deps)
        await fetcher.fetch(series_id="GDP")

        repo = configured_fetcher_deps["quality_repo"]
        latest = repo.read_latest("GDP")  # type: ignore[attr-defined]
        assert latest is not None
        assert latest.series_kind == "macro"


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline order (Rule 12 INVARIABILE)
# ═══════════════════════════════════════════════════════════════════════════
class TestPipelineOrderEnforced:
    """The order rate_limit → fetch → clean → write → quality is enforced."""

    @pytest.mark.asyncio
    async def test_rate_limiter_acquired_before_fetch(
        self,
        configured_fetcher_deps: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If rate-limiter acquire fails, _fetch_raw_ohlcv must NOT be called."""
        fetcher = _StubOhlcvFetcher(df=_ohlcv_df(10), **configured_fetcher_deps)

        # Simuliamo il fallimento del rate limiter
        async def _failing_acquire(_source: str) -> None:
            raise RuntimeError("rate limit exhausted")

        monkeypatch.setattr(fetcher._rate_limiter, "acquire", _failing_acquire)

        with pytest.raises(FetchError):
            await fetcher.fetch(ticker="X", exchange="Y", timeframe="1d")

        # _fetch_raw_ohlcv NON deve essere stato invocato (gate prima della rete)
        assert fetcher.fetch_call_count == 0
