"""Tests for shared.db.prices_repo."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pandas as pd
import pytest

from shared.db.duckdb_client import DuckDBClient
from shared.db.duckdb_migrator import DuckDBMigrator
from shared.db.prices_repo import PricesRepository
from shared.exceptions import DataValidationError
from shared.types import TimeFrame

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def prices_repo(tmp_duckdb_path: Path) -> PricesRepository:
    """Fresh DuckDB with schema applied + PricesRepository bound to it."""
    client = DuckDBClient(path=tmp_duckdb_path)
    from shared.constants import MIGRATIONS_DUCKDB_DIR
    DuckDBMigrator(client=client, migrations_dir=MIGRATIONS_DUCKDB_DIR).apply_pending()
    return PricesRepository(client=client)


def _sample_ohlcv(n: int = 10, start: datetime | None = None) -> pd.DataFrame:
    """Build a valid OHLCV DataFrame for tests."""
    if start is None:
        start = datetime(2025, 1, 1, tzinfo=UTC)
    # Timestamp UTC-aware con intervallo giornaliero
    ts = pd.date_range(start=start, periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "ts": ts,
            "open": [100.0 + i for i in range(n)],
            "high": [101.0 + i for i in range(n)],
            "low": [99.0 + i for i in range(n)],
            "close": [100.5 + i for i in range(n)],
            "volume": [1_000_000 + i * 1000 for i in range(n)],
            "adj_close": [100.5 + i for i in range(n)],
        }
    )


class TestWriteOhlcv:
    def test_write_simple_dataframe(self, prices_repo: PricesRepository) -> None:
        df = _sample_ohlcv(5)
        n = prices_repo.write_ohlcv(
            ticker="AAPL",
            exchange="NASDAQ",
            timeframe=TimeFrame.D1,
            df=df,
            source="test",
        )
        assert n == 5
        assert prices_repo.count_bars("AAPL") == 5

    def test_write_empty_dataframe(self, prices_repo: PricesRepository) -> None:
        df = pd.DataFrame(
            {
                "ts": pd.Series([], dtype="datetime64[ns, UTC]"),
                "open": pd.Series([], dtype="float64"),
                "high": pd.Series([], dtype="float64"),
                "low": pd.Series([], dtype="float64"),
                "close": pd.Series([], dtype="float64"),
                "volume": pd.Series([], dtype="int64"),
            }
        )
        n = prices_repo.write_ohlcv(
            ticker="EMPTY",
            exchange="X",
            timeframe="1d",
            df=df,
            source="test",
        )
        assert n == 0

    def test_write_is_idempotent_upsert(self, prices_repo: PricesRepository) -> None:
        """Re-writing same keys should REPLACE, not duplicate."""
        df = _sample_ohlcv(5)
        prices_repo.write_ohlcv("MSFT", "NASDAQ", TimeFrame.D1, df, source="test")
        # 2° write: stessi timestamps, valori diversi — deve sovrascrivere
        df2 = df.copy()
        df2["close"] = df2["close"] + 10.0
        prices_repo.write_ohlcv("MSFT", "NASDAQ", TimeFrame.D1, df2, source="test")

        assert prices_repo.count_bars("MSFT") == 5  # non 10 (upsert idempotente)
        latest = prices_repo.read_latest_price("MSFT")
        assert latest is not None
        # Il close più recente dev'essere quello della 2ª scrittura
        assert latest["close"] == pytest.approx(df2["close"].iloc[-1])

    def test_write_rejects_invalid_schema(self, prices_repo: PricesRepository) -> None:
        """Regola 9: ogni DataFrame validato da Pandera."""
        bad = pd.DataFrame(
            {
                "ts": pd.date_range("2025-01-01", periods=3, tz="UTC"),
                # open mancante → schema violation
                "high": [1.0, 2.0, 3.0],
                "low": [0.5, 1.5, 2.5],
                "close": [1.0, 2.0, 3.0],
                "volume": [100, 200, 300],
            }
        )
        with pytest.raises(DataValidationError):
            prices_repo.write_ohlcv("BAD", "X", "1d", bad, source="test")

    def test_write_rejects_negative_prices(self, prices_repo: PricesRepository) -> None:
        bad = _sample_ohlcv(3)
        bad.loc[0, "low"] = -10.0
        with pytest.raises(DataValidationError):
            prices_repo.write_ohlcv("BAD", "X", "1d", bad, source="test")


class TestReadPrices:
    def test_read_returns_all_bars(self, prices_repo: PricesRepository) -> None:
        df = _sample_ohlcv(10)
        prices_repo.write_ohlcv("GOOG", "NASDAQ", TimeFrame.D1, df, source="test")

        result = prices_repo.read_prices("GOOG", exchange="NASDAQ", timeframe=TimeFrame.D1)
        assert len(result) == 10
        # Colonne attese presenti
        for col in ["ts", "open", "high", "low", "close", "volume"]:
            assert col in result.columns

    def test_read_with_date_range_filter(self, prices_repo: PricesRepository) -> None:
        df = _sample_ohlcv(20, start=datetime(2025, 1, 1, tzinfo=UTC))
        prices_repo.write_ohlcv("TSLA", "NASDAQ", "1d", df, source="test")

        # Filtro: solo bar tra il 5 e il 10 gennaio
        start = datetime(2025, 1, 5, tzinfo=UTC)
        end = datetime(2025, 1, 10, tzinfo=UTC)
        result = prices_repo.read_prices(
            "TSLA",
            exchange="NASDAQ",
            timeframe="1d",
            start=start,
            end=end,
        )
        # Da 5 gennaio a 10 gennaio inclusi = 6 barre
        assert len(result) == 6

    def test_read_returns_empty_for_missing_ticker(
        self, prices_repo: PricesRepository
    ) -> None:
        result = prices_repo.read_prices("NONEXISTENT")
        assert result.empty

    def test_read_results_sorted_by_ts(self, prices_repo: PricesRepository) -> None:
        df = _sample_ohlcv(15)
        prices_repo.write_ohlcv("META", "NASDAQ", "1d", df, source="test")
        result = prices_repo.read_prices("META", timeframe="1d")
        assert result["ts"].is_monotonic_increasing


class TestLatestPrice:
    def test_returns_most_recent_bar(self, prices_repo: PricesRepository) -> None:
        df = _sample_ohlcv(10)
        prices_repo.write_ohlcv("NVDA", "NASDAQ", "1d", df, source="test")

        latest = prices_repo.read_latest_price("NVDA")
        assert latest is not None
        # L'ultimo bar è il 10° giorno, close = 109.5
        assert latest["close"] == pytest.approx(109.5)

    def test_returns_none_for_missing_ticker(
        self, prices_repo: PricesRepository
    ) -> None:
        assert prices_repo.read_latest_price("GHOST") is None


class TestDeletePrices:
    def test_delete_removes_old_bars(self, prices_repo: PricesRepository) -> None:
        df = _sample_ohlcv(20, start=datetime(2025, 1, 1, tzinfo=UTC))
        prices_repo.write_ohlcv("AMD", "NASDAQ", "1d", df, source="test")
        assert prices_repo.count_bars("AMD") == 20

        # Eliminiamo bar anteriori al 10 gennaio (9 barre attese)
        cutoff = datetime(2025, 1, 10, tzinfo=UTC)
        deleted = prices_repo.delete_prices("AMD", before_ts=cutoff)
        assert deleted == 9
        assert prices_repo.count_bars("AMD") == 11

    def test_delete_no_op_when_no_match(self, prices_repo: PricesRepository) -> None:
        deleted = prices_repo.delete_prices(
            "NOTHING_HERE", before_ts=datetime(2025, 1, 1, tzinfo=UTC)
        )
        assert deleted == 0


@pytest.mark.benchmark
class TestPricesPerformance:
    """Performance targets from Fase 1 DoD.

    Targets:
      · DuckDB write 10k rows: < 500ms
      · DuckDB query 10 years single ticker: < 200ms (~2520 daily bars)
    """

    def test_write_10k_rows_under_500ms(self, prices_repo: PricesRepository) -> None:
        """Write 10k OHLCV rows and check latency."""
        import time

        df = _sample_ohlcv(10_000, start=datetime(2000, 1, 1, tzinfo=UTC))

        t0 = time.monotonic()
        n = prices_repo.write_ohlcv("PERF", "NYSE", "1d", df, source="test")
        elapsed_ms = (time.monotonic() - t0) * 1000

        assert n == 10_000
        # Target DoD: < 500ms
        assert elapsed_ms < 500, f"expected <500ms, got {elapsed_ms:.1f}ms"

    def test_read_10y_prices_under_200ms(self, prices_repo: PricesRepository) -> None:
        """Query 10 years of daily bars and check latency."""
        import time

        # 10 anni di daily bar = 10 * 252 ≈ 2520 barre (usiamo calendar days, 3650)
        df = _sample_ohlcv(3650, start=datetime(2015, 1, 1, tzinfo=UTC))
        prices_repo.write_ohlcv("SPY", "NYSE", "1d", df, source="test")

        t0 = time.monotonic()
        result = prices_repo.read_prices(
            "SPY",
            exchange="NYSE",
            timeframe="1d",
            start=datetime(2015, 1, 1, tzinfo=UTC),
            end=datetime(2024, 12, 31, tzinfo=UTC),
        )
        elapsed_ms = (time.monotonic() - t0) * 1000

        assert len(result) >= 3600
        # Target DoD: < 200ms
        assert elapsed_ms < 200, f"expected <200ms, got {elapsed_ms:.1f}ms"
