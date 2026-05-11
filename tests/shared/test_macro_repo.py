"""Tests for shared.db.macro_repo."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pandas as pd
import pytest

from shared.db.duckdb_client import DuckDBClient
from shared.db.duckdb_migrator import DuckDBMigrator
from shared.db.macro_repo import MacroRepository
from shared.exceptions import DataValidationError

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def macro_repo(tmp_duckdb_path: Path) -> MacroRepository:
    """Fresh DuckDB with schema + MacroRepository."""
    client = DuckDBClient(path=tmp_duckdb_path)
    from shared.constants import MIGRATIONS_DUCKDB_DIR
    DuckDBMigrator(client=client, migrations_dir=MIGRATIONS_DUCKDB_DIR).apply_pending()
    return MacroRepository(client=client)


def _sample_macro(n: int = 12, start: datetime | None = None) -> pd.DataFrame:
    """Build a valid macro-series DataFrame (monthly)."""
    if start is None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
    ts = pd.date_range(start=start, periods=n, freq="MS", tz="UTC")
    return pd.DataFrame({"ts": ts, "value": [float(i) * 1.5 for i in range(n)]})


class TestWriteMacroSeries:
    def test_write_simple(self, macro_repo: MacroRepository) -> None:
        df = _sample_macro(12)
        n = macro_repo.write_macro_series(
            "UNRATE", df=df, source="fred", unit="Percent", frequency="M"
        )
        assert n == 12
        assert macro_repo.count_observations("UNRATE") == 12

    def test_write_with_nan_values_allowed(self, macro_repo: MacroRepository) -> None:
        """FRED a volte rilascia serie con NaN per dati non disponibili."""
        df = _sample_macro(5)
        df.loc[2, "value"] = float("nan")
        n = macro_repo.write_macro_series("CPI", df, source="fred")
        assert n == 5

    def test_write_is_idempotent(self, macro_repo: MacroRepository) -> None:
        df = _sample_macro(6)
        macro_repo.write_macro_series("GDP", df, source="fred")
        # 2ª scrittura con stessi ts → upsert, non duplicato
        df2 = df.copy()
        df2["value"] = df2["value"] + 100
        macro_repo.write_macro_series("GDP", df2, source="fred")

        assert macro_repo.count_observations("GDP") == 6
        latest = macro_repo.read_latest_macro("GDP")
        assert latest is not None
        # Il valore aggiornato deve prevalere
        assert latest["value"] == pytest.approx(df2["value"].iloc[-1])

    def test_write_rejects_invalid_schema(self, macro_repo: MacroRepository) -> None:
        # DataFrame senza colonna "ts" → schema violation
        bad = pd.DataFrame({"timestamp": [1, 2], "value": [10.0, 20.0]})
        with pytest.raises(DataValidationError):
            macro_repo.write_macro_series("BAD", bad, source="fred")

    def test_empty_dataframe_returns_zero(self, macro_repo: MacroRepository) -> None:
        df = pd.DataFrame(
            {
                "ts": pd.Series([], dtype="datetime64[ns, UTC]"),
                "value": pd.Series([], dtype="float64"),
            }
        )
        assert macro_repo.write_macro_series("EMPTY", df, source="fred") == 0


class TestReadMacro:
    def test_read_returns_sorted_series(self, macro_repo: MacroRepository) -> None:
        df = _sample_macro(12)
        macro_repo.write_macro_series("M2", df, source="fred", frequency="M")
        result = macro_repo.read_macro("M2")
        assert len(result) == 12
        assert result["ts"].is_monotonic_increasing

    def test_read_with_date_filters(self, macro_repo: MacroRepository) -> None:
        df = _sample_macro(24, start=datetime(2023, 1, 1, tzinfo=UTC))
        macro_repo.write_macro_series("PAYEMS", df, source="fred", frequency="M")

        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 6, 30, tzinfo=UTC)
        result = macro_repo.read_macro("PAYEMS", start=start, end=end)
        assert len(result) == 6  # Gennaio-Giugno 2024

    def test_read_empty_for_missing_series(self, macro_repo: MacroRepository) -> None:
        result = macro_repo.read_macro("DOES_NOT_EXIST")
        assert result.empty


class TestLatestMacro:
    def test_returns_most_recent(self, macro_repo: MacroRepository) -> None:
        df = _sample_macro(12)
        macro_repo.write_macro_series(
            "FEDFUNDS", df, source="fred", unit="Percent", frequency="M"
        )
        latest = macro_repo.read_latest_macro("FEDFUNDS")
        assert latest is not None
        assert latest["series_id"] == "FEDFUNDS"
        assert latest["unit"] == "Percent"

    def test_returns_none_for_missing(self, macro_repo: MacroRepository) -> None:
        assert macro_repo.read_latest_macro("NONE") is None


class TestListSeries:
    def test_list_all(self, macro_repo: MacroRepository) -> None:
        macro_repo.write_macro_series("A", _sample_macro(3), source="fred")
        macro_repo.write_macro_series("B", _sample_macro(3), source="ecb")
        series = macro_repo.list_series()
        assert set(series) == {"A", "B"}

    def test_list_filtered_by_source(self, macro_repo: MacroRepository) -> None:
        macro_repo.write_macro_series("US1", _sample_macro(3), source="fred")
        macro_repo.write_macro_series("US2", _sample_macro(3), source="fred")
        macro_repo.write_macro_series("EU1", _sample_macro(3), source="ecb")

        fred_only = macro_repo.list_series(source="fred")
        assert set(fred_only) == {"US1", "US2"}
