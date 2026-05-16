"""Tests for engine.market_data.fetchers.fred_fetcher."""
from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pandas as pd
import pytest

from engine.market_data.fetchers.fred_fetcher import FRED_KEY_SERIES, FREDFetcher
from shared.constants import MIGRATIONS_DUCKDB_DIR
from shared.db.dual_writer import DualWriter
from shared.db.duckdb_client import DuckDBClient
from shared.db.duckdb_migrator import DuckDBMigrator
from shared.db.macro_repo import MacroRepository
from shared.db.prices_repo import PricesRepository
from shared.db.quality import QualityReportRepository
from shared.exceptions import FetchError
from shared.rate_limit_manager import RateLimitManager

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def fred_deps(tmp_duckdb_path: Path, tmp_path: Path) -> dict[str, object]:
    client = DuckDBClient(path=tmp_duckdb_path)
    DuckDBMigrator(client=client, migrations_dir=MIGRATIONS_DUCKDB_DIR).apply_pending()

    rate_limits = tmp_path / "rate_limits.yaml"
    rate_limits.write_text(
        "fred:\n"
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
        "api_key": "test_key_fake",
    }


def _fred_raw(n: int = 12) -> pd.DataFrame:
    """Mimic pandas-datareader DataReader output for FRED."""
    # pandas-datareader restituisce DatetimeIndex tz-naive con un'unica colonna
    # nominata come la series_id (es. "UNRATE").
    idx = pd.date_range(start="2024-01-01", periods=n, freq="MS")
    return pd.DataFrame({"UNRATE": [3.5 + 0.1 * i for i in range(n)]}, index=idx)


class TestFREDKeySeries:
    def test_catalog_not_empty(self) -> None:
        assert len(FRED_KEY_SERIES) >= 40

    def test_catalog_has_no_duplicates(self) -> None:
        assert len(FRED_KEY_SERIES) == len(set(FRED_KEY_SERIES))

    def test_catalog_includes_core_series(self) -> None:
        # Le serie FRED più note devono esserci
        for series in ("GDP", "UNRATE", "CPIAUCSL", "FEDFUNDS", "DGS10"):
            assert series in FRED_KEY_SERIES


class TestFREDFetcherNormalization:
    def test_normalize_adds_utc_timezone(self) -> None:
        raw = _fred_raw(6)
        out = FREDFetcher._normalize_fred_frame(raw, "UNRATE")
        # Regola 19: ts deve essere UTC-aware
        assert out["ts"].dt.tz is not None
        assert "value" in out.columns

    def test_normalize_handles_periods_correctly(self) -> None:
        raw = _fred_raw(3)
        out = FREDFetcher._normalize_fred_frame(raw, "UNRATE")
        assert len(out) == 3

    def test_value_dtype_is_float64(self) -> None:
        raw = _fred_raw(5)
        out = FREDFetcher._normalize_fred_frame(raw, "GDP")
        assert out["value"].dtype == "float64"


class TestFREDFetcherPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline(self, fred_deps: dict[str, object]) -> None:
        fetcher = FREDFetcher(**fred_deps)  # type: ignore[arg-type]
        with patch.object(FREDFetcher, "_download_sync", return_value=_fred_raw(12)):
            outcome = await fetcher.fetch(
                series_id="UNRATE", unit="Percent", frequency="M"
            )
        assert outcome.write_result.rows_written == 12
        assert outcome.report.series_kind == "macro"

    @pytest.mark.asyncio
    async def test_empty_response_returns_zero(
        self, fred_deps: dict[str, object]
    ) -> None:
        fetcher = FREDFetcher(**fred_deps)  # type: ignore[arg-type]
        with patch.object(FREDFetcher, "_download_sync", return_value=pd.DataFrame()):
            outcome = await fetcher.fetch(series_id="EMPTY")
        assert outcome.write_result.rows_written == 0

    @pytest.mark.asyncio
    async def test_pdr_exception_normalised_to_fetch_error(
        self, fred_deps: dict[str, object]
    ) -> None:
        fetcher = FREDFetcher(**fred_deps)  # type: ignore[arg-type]
        with patch.object(
            FREDFetcher, "_download_sync", side_effect=ValueError("series not found")
        ), pytest.raises(FetchError):
            await fetcher.fetch(series_id="NONEXISTENT")

    def test_api_key_read_from_env(
        self, fred_deps: dict[str, object], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Regola 15: api_key da env, mai hardcoded
        monkeypatch.setenv("FRED_API_KEY", "env_key_xxx")
        deps = {k: v for k, v in fred_deps.items() if k != "api_key"}
        fetcher = FREDFetcher(**deps)  # type: ignore[arg-type]
        assert fetcher._api_key == "env_key_xxx"


class TestFREDFetcherDownloadSync:
    def test_download_sync_calls_pdr_with_dates(self, fred_deps: dict[str, object]) -> None:
        """_download_sync formats dates correctly for pandas-datareader."""
        fetcher = FREDFetcher(**fred_deps)  # type: ignore[arg-type]
        from datetime import datetime, timezone
        mock_df = _fred_raw(3)
        with patch("pandas_datareader.data.DataReader", return_value=mock_df) as mock_pdr:
            result = fetcher._download_sync(
                series_id="UNRATE",
                start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end=datetime(2024, 6, 1, tzinfo=timezone.utc),
            )
        assert result is not None
        mock_pdr.assert_called_once()
        kwargs = mock_pdr.call_args.kwargs
        assert kwargs["name"] == "UNRATE"
        assert kwargs["data_source"] == "fred"
        assert "start" in kwargs
        assert "end" in kwargs

    def test_download_sync_without_dates(self, fred_deps: dict[str, object]) -> None:
        """No start/end provided → no date kwargs sent to pdr."""
        fetcher = FREDFetcher(**fred_deps)  # type: ignore[arg-type]
        mock_df = _fred_raw(3)
        with patch("pandas_datareader.data.DataReader", return_value=mock_df) as mock_pdr:
            fetcher._download_sync(series_id="UNRATE", start=None, end=None)
        kwargs = mock_pdr.call_args.kwargs
        assert "start" not in kwargs
        assert "end" not in kwargs

    def test_download_sync_includes_api_key(self, fred_deps: dict[str, object]) -> None:
        """api_key passed to pdr.DataReader as kwarg."""
        fetcher = FREDFetcher(**fred_deps)  # type: ignore[arg-type]
        mock_df = _fred_raw(3)
        with patch("pandas_datareader.data.DataReader", return_value=mock_df) as mock_pdr:
            fetcher._download_sync(series_id="UNRATE", start=None, end=None)
        kwargs = mock_pdr.call_args.kwargs
        assert kwargs.get("api_key") == "test_key_fake"


class TestFREDFetcherNormalizationEdgeCases:
    def test_normalize_already_tz_aware(self) -> None:
        """Frame con timestamp già UTC-aware viene mantenuto come UTC."""
        idx = pd.date_range("2024-01-01", periods=3, freq="MS", tz="US/Eastern")
        raw = pd.DataFrame({"UNRATE": [3.5, 3.6, 3.7]}, index=idx)
        out = FREDFetcher._normalize_fred_frame(raw, "UNRATE")
        # Should be converted to UTC
        assert str(out["ts"].dt.tz) == "UTC"

    def test_normalize_raises_on_single_col_frame(self) -> None:
        """Frame con solo timestamp e nessuna colonna valore → FetchError."""
        # Pandas-datareader returns df with index as date and 1 value col,
        # but if reset_index gives only one column, that's an unexpected frame
        df = pd.DataFrame({"DATE": pd.date_range("2024-01-01", periods=3)})
        df.set_index("DATE", inplace=True)
        # df has no value columns after reset → triggers FetchError path
        # But _normalize_fred_frame uses reset_index first; with no value cols
        # the "DATE" col is the only one and there's no value_col_candidate
        with pytest.raises(FetchError):
            FREDFetcher._normalize_fred_frame(df, "UNRATE")
