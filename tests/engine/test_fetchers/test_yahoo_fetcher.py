"""Tests for engine.market_data.fetchers.yahoo_fetcher."""
from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pandas as pd
import pytest

from engine.market_data.fetchers.yahoo_fetcher import YahooFetcher
from shared.constants import MIGRATIONS_DUCKDB_DIR
from shared.db.dual_writer import DualWriter
from shared.db.duckdb_client import DuckDBClient
from shared.db.duckdb_migrator import DuckDBMigrator
from shared.db.macro_repo import MacroRepository
from shared.db.prices_repo import PricesRepository
from shared.db.quality import QualityReportRepository
from shared.exceptions import FetchError
from shared.rate_limit_manager import RateLimitManager
from shared.types import TimeFrame

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def fetcher_deps(tmp_duckdb_path: Path, tmp_path: Path) -> dict[str, object]:
    """Wire DuckDB + permissive rate limiter + cache for an end-to-end test."""
    client = DuckDBClient(path=tmp_duckdb_path)
    DuckDBMigrator(client=client, migrations_dir=MIGRATIONS_DUCKDB_DIR).apply_pending()

    rate_limits = tmp_path / "rate_limits.yaml"
    rate_limits.write_text(
        "yahoo_finance:\n"
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
    }


def _yahoo_raw(n: int = 30) -> pd.DataFrame:
    """Mimic the shape of yfinance.download output."""
    # yfinance restituisce DatetimeIndex con tz-naive (US/Eastern) e
    # colonne ['Open','High','Low','Close','Adj Close','Volume']
    idx = pd.date_range(start="2025-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(n)],
            "High": [101.0 + i for i in range(n)],
            "Low": [99.0 + i for i in range(n)],
            "Close": [100.5 + i for i in range(n)],
            "Adj Close": [100.5 + i for i in range(n)],
            "Volume": [1_000_000 + i * 1000 for i in range(n)],
        },
        index=idx,
    )


class TestYahooFetcherNormalization:
    def test_normalize_yahoo_frame_canonical_shape(self) -> None:
        raw = _yahoo_raw(10)
        out = YahooFetcher._normalize_yahoo_frame(raw)
        # Colonne canoniche
        for col in ("ts", "open", "high", "low", "close", "volume", "adj_close"):
            assert col in out.columns
        # ts deve essere tz-aware UTC (Regola 19)
        assert out["ts"].dt.tz is not None

    def test_volume_cast_to_int64(self) -> None:
        raw = _yahoo_raw(5)
        out = YahooFetcher._normalize_yahoo_frame(raw)
        assert out["volume"].dtype == "int64"

    def test_drops_all_nan_price_rows(self) -> None:
        raw = _yahoo_raw(5)
        # Inserisci una riga di soli NaN (festività Yahoo)
        raw.loc[raw.index[2], ["Open", "High", "Low", "Close"]] = float("nan")
        out = YahooFetcher._normalize_yahoo_frame(raw)
        assert len(out) == 4


class TestYahooFetcherPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline_with_mocked_yfinance(
        self, fetcher_deps: dict[str, object]
    ) -> None:
        fetcher = YahooFetcher(**fetcher_deps)  # type: ignore[arg-type]
        # Patch del metodo statico _download_sync per evitare la rete
        with patch.object(YahooFetcher, "_download_sync", return_value=_yahoo_raw(30)):
            outcome = await fetcher.fetch(
                ticker="AAPL", exchange="NASDAQ", timeframe=TimeFrame.D1
            )
        assert outcome.write_result.rows_written == 30
        assert outcome.report.series_id == "AAPL"
        assert outcome.report.series_kind == "prices"

    @pytest.mark.asyncio
    async def test_empty_response_handled(
        self, fetcher_deps: dict[str, object]
    ) -> None:
        fetcher = YahooFetcher(**fetcher_deps)  # type: ignore[arg-type]
        with patch.object(YahooFetcher, "_download_sync", return_value=pd.DataFrame()):
            outcome = await fetcher.fetch(
                ticker="GHOST", exchange="X", timeframe=TimeFrame.D1
            )
        assert outcome.write_result.rows_written == 0

    @pytest.mark.asyncio
    async def test_yfinance_exception_becomes_fetch_error(
        self, fetcher_deps: dict[str, object]
    ) -> None:
        fetcher = YahooFetcher(**fetcher_deps)  # type: ignore[arg-type]
        with patch.object(
            YahooFetcher, "_download_sync", side_effect=KeyError("garbled response")
        ), pytest.raises(FetchError):
            await fetcher.fetch(
                ticker="X", exchange="Y", timeframe=TimeFrame.D1
            )

    @pytest.mark.asyncio
    async def test_rate_limiter_acquired(
        self, fetcher_deps: dict[str, object]
    ) -> None:
        """Verifica che il rate limiter sia chiamato prima di scaricare."""
        fetcher = YahooFetcher(**fetcher_deps)  # type: ignore[arg-type]
        rate_limiter = fetcher_deps["rate_limiter"]
        before = rate_limiter.get_status("yahoo_finance")["daily_used"]  # type: ignore[index,attr-defined]

        with patch.object(YahooFetcher, "_download_sync", return_value=_yahoo_raw(5)):
            await fetcher.fetch(ticker="MSFT", exchange="NASDAQ", timeframe="1d")

        after = rate_limiter.get_status("yahoo_finance")["daily_used"]  # type: ignore[index,attr-defined]
        assert after == before + 1
