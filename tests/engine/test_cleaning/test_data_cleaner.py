"""Tests for engine.market_data.cleaning.data_cleaner."""
from __future__ import annotations

import time
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from engine.market_data.cleaning import CleaningResult, DataCleaner
from shared.exceptions import DataCleaningError


def _ohlcv(
    n: int = 100, start: datetime | None = None, with_outliers: bool = False
) -> pd.DataFrame:
    """Realistic OHLCV factory with optional injected outliers."""
    rng = np.random.default_rng(seed=12345)
    if start is None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
    ts = pd.date_range(start=start, periods=n, freq="D", tz="UTC")
    # Random walk geometrico per i prezzi (più realistico di valori costanti)
    log_returns = rng.normal(0.0005, 0.01, size=n)
    close = 100.0 * np.exp(np.cumsum(log_returns))
    if with_outliers and n > 20:
        # Inietta un outlier estremo a metà serie
        close[n // 2] *= 2.0
    return pd.DataFrame(
        {
            "ts": ts,
            "open": close * 0.999,
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": rng.integers(900_000, 1_100_000, size=n),
            "adj_close": close,
        }
    )


def _macro(n: int = 60, with_nan: bool = False) -> pd.DataFrame:
    ts = pd.date_range(start="2020-01-01", periods=n, freq="MS", tz="UTC")
    values = [3.0 + 0.05 * i for i in range(n)]
    if with_nan and n > 5:
        values[3] = float("nan")
    return pd.DataFrame({"ts": ts, "value": values})


# ═══════════════════════════════════════════════════════════════════════════
# OHLCV pipeline tests
# ═══════════════════════════════════════════════════════════════════════════
class TestCleanOhlcv:
    def test_clean_returns_cleaning_result(self) -> None:
        cleaner = DataCleaner()
        result = cleaner.clean_ohlcv(_ohlcv(50), ticker="AAPL")
        assert isinstance(result, CleaningResult)
        assert result.report.series_id == "AAPL"
        assert result.report.series_kind == "prices"
        assert result.cleaned_df.shape[0] == 50

    def test_quality_score_in_range(self) -> None:
        cleaner = DataCleaner()
        result = cleaner.clean_ohlcv(_ohlcv(100), ticker="MSFT")
        assert 0.0 <= result.report.quality_score <= 1.0

    def test_clean_data_yields_high_score(self) -> None:
        # Serie senza gap, senza outlier, fresca → score alto
        recent_start = datetime(2026, 1, 1, tzinfo=UTC)
        cleaner = DataCleaner()
        result = cleaner.clean_ohlcv(_ohlcv(100, start=recent_start), ticker="GOOG")
        # Dati clean + recenti dovrebbero avere score >= 0.5 (Regola 26 critical)
        assert result.report.quality_score >= 0.5

    def test_outliers_detected(self) -> None:
        cleaner = DataCleaner()
        result = cleaner.clean_ohlcv(_ohlcv(100, with_outliers=True), ticker="TSLA")
        # Almeno 1 outlier flaggato (il valore 2x iniettato)
        assert result.outlier_mask.sum() >= 1

    def test_duplicates_dropped(self) -> None:
        cleaner = DataCleaner()
        df = _ohlcv(20)
        # Inseriamo un duplicato
        df_dup = pd.concat([df, df.iloc[[5]]], ignore_index=True)
        result = cleaner.clean_ohlcv(df_dup, ticker="AMZN")
        # Dopo cleaning: stessa lunghezza dell'originale (duplicato rimosso)
        assert len(result.cleaned_df) == 20

    def test_empty_dataframe_returns_zero_report(self) -> None:
        cleaner = DataCleaner()
        result = cleaner.clean_ohlcv(pd.DataFrame(), ticker="EMPTY")
        assert result.report.total_rows == 0
        assert result.cleaned_df.empty

    def test_missing_required_columns_raises(self) -> None:
        cleaner = DataCleaner()
        bad = pd.DataFrame({"ts": pd.date_range("2025-01-01", periods=3, tz="UTC")})
        with pytest.raises(DataCleaningError):
            cleaner.clean_ohlcv(bad, ticker="BAD")


# ═══════════════════════════════════════════════════════════════════════════
# Macro pipeline tests
# ═══════════════════════════════════════════════════════════════════════════
class TestCleanMacro:
    def test_clean_macro_returns_result(self) -> None:
        cleaner = DataCleaner()
        result = cleaner.clean_macro(_macro(60), series_id="UNRATE")
        assert result.report.series_kind == "macro"
        assert result.report.total_rows == 60

    def test_macro_with_nan_counted_as_gap(self) -> None:
        cleaner = DataCleaner()
        result = cleaner.clean_macro(_macro(20, with_nan=True), series_id="GDP")
        # gaps_count include i NaN (release mancanti FRED)
        assert result.report.gaps_count >= 1

    def test_macro_empty_returns_zero(self) -> None:
        cleaner = DataCleaner()
        result = cleaner.clean_macro(pd.DataFrame(), series_id="EMPTY")
        assert result.report.total_rows == 0


# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════
class TestCleanerConfiguration:
    def test_works_with_default_config(self) -> None:
        cleaner = DataCleaner()
        # Esegue senza errori anche senza override config
        result = cleaner.clean_ohlcv(_ohlcv(30), ticker="X")
        assert result.report.total_rows == 30


# ═══════════════════════════════════════════════════════════════════════════
# Performance — Fase 2 DoD
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.benchmark
class TestPerformance:
    """DoD Fase 2: DataQualityReport generation < 1s on 10y of daily data."""

    def test_10y_daily_under_1s(self) -> None:
        """3650 daily bars (~10 years) cleaned + report in < 1s."""
        cleaner = DataCleaner()
        df = _ohlcv(3650, start=datetime(2015, 1, 1, tzinfo=UTC))

        t0 = time.monotonic()
        result = cleaner.clean_ohlcv(df, ticker="SPY")
        elapsed_ms = (time.monotonic() - t0) * 1000

        assert result.report.total_rows == 3650
        # Target DoD: < 1s
        assert elapsed_ms < 1000, f"expected <1000ms, got {elapsed_ms:.1f}ms"
