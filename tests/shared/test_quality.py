"""Tests for shared.db.quality (DataQualityReport + persistence)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from shared.constants import MIGRATIONS_DUCKDB_DIR
from shared.db.duckdb_client import DuckDBClient
from shared.db.duckdb_migrator import DuckDBMigrator
from shared.db.quality import (
    DataQualityReport,
    QualityReportRepository,
    QualityScoringConfig,
    load_quality_config,
)
from shared.exceptions import ConfigurationError, DataQualityError

if TYPE_CHECKING:
    from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════════
# Score computation
# ═══════════════════════════════════════════════════════════════════════════
class TestComputeScore:
    def test_perfect_data_yields_score_one(self) -> None:
        report = DataQualityReport.compute(
            series_id="X",
            series_kind="prices",
            total_rows=1000,
            gaps_count=0,
            outliers_count=0,
            stale_days=0,
            duplicates_count=0,
        )
        assert report.quality_score == pytest.approx(1.0)

    def test_score_decreases_with_issues(self) -> None:
        bad = DataQualityReport.compute(
            series_id="X",
            series_kind="prices",
            total_rows=100,
            gaps_count=20,
            outliers_count=10,
            stale_days=10,
            duplicates_count=5,
        )
        good = DataQualityReport.compute(
            series_id="X",
            series_kind="prices",
            total_rows=100,
        )
        assert bad.quality_score < good.quality_score

    def test_score_clipped_to_zero(self) -> None:
        # Caso patologico: 100% gaps + 100% outliers → score=0, non negativo
        report = DataQualityReport.compute(
            series_id="X",
            series_kind="prices",
            total_rows=10,
            gaps_count=10,
            outliers_count=10,
            stale_days=10000,
            duplicates_count=10,
        )
        assert 0.0 <= report.quality_score <= 1.0

    def test_zero_rows_no_division_error(self) -> None:
        # Protezione: total_rows=0 non deve causare ZeroDivisionError
        report = DataQualityReport.compute(
            series_id="X",
            series_kind="prices",
            total_rows=0,
        )
        assert isinstance(report.quality_score, float)


# ═══════════════════════════════════════════════════════════════════════════
# Acceptance thresholds (Rule 26)
# ═══════════════════════════════════════════════════════════════════════════
class TestAcceptanceThresholds:
    def test_acceptable_for_critical_default(self) -> None:
        report = DataQualityReport.compute(
            series_id="X", series_kind="prices", total_rows=100
        )
        assert report.is_acceptable_for_critical()  # score=1.0 ≥ 0.5

    def test_low_score_fails_critical(self) -> None:
        report = DataQualityReport(
            series_id="X",
            series_kind="prices",
            quality_score=0.3,
            total_rows=100,
        )
        assert not report.is_acceptable_for_critical()

    def test_assert_critical_raises_on_low_score(self) -> None:
        report = DataQualityReport(
            series_id="X",
            series_kind="prices",
            quality_score=0.3,
            total_rows=100,
        )
        with pytest.raises(DataQualityError) as exc:
            report.assert_critical()
        # Verifica che il messaggio contenga lo score reale
        assert "0.300" in str(exc.value) or "0.3" in str(exc.value)


# ═══════════════════════════════════════════════════════════════════════════
# Configuration loading
# ═══════════════════════════════════════════════════════════════════════════
class TestQualityScoringConfig:
    def test_weights_must_sum_to_one(self) -> None:
        with pytest.raises(ConfigurationError):
            QualityScoringConfig(
                weight_completeness=0.5,
                weight_outlier_purity=0.5,
                weight_freshness=0.5,
                weight_uniqueness=0.5,  # sum=2.0 → error
                max_stale_days=5,
                min_score_critical=0.5,
                min_score_backtest=0.7,
                warn_score=0.8,
            )

    def test_load_default_config(self) -> None:
        # Carica config/data_quality.yaml dal progetto
        cfg = load_quality_config()
        # I pesi devono sommare a 1
        total = (
            cfg.weight_completeness
            + cfg.weight_outlier_purity
            + cfg.weight_freshness
            + cfg.weight_uniqueness
        )
        assert 0.99 <= total <= 1.01

    def test_load_missing_returns_defaults(self, tmp_path: Path) -> None:
        cfg = load_quality_config(tmp_path / "missing.yaml")
        assert cfg.warn_score == 0.8


# ═══════════════════════════════════════════════════════════════════════════
# Persistence
# ═══════════════════════════════════════════════════════════════════════════
@pytest.fixture
def quality_repo(tmp_duckdb_path: Path) -> QualityReportRepository:
    """Fresh DuckDB with schema + repo bound to it."""
    client = DuckDBClient(path=tmp_duckdb_path)
    DuckDBMigrator(client=client, migrations_dir=MIGRATIONS_DUCKDB_DIR).apply_pending()
    return QualityReportRepository(client=client)


class TestQualityReportPersistence:
    def test_write_and_read_back(
        self, quality_repo: QualityReportRepository
    ) -> None:
        report = DataQualityReport.compute(
            series_id="AAPL",
            series_kind="prices",
            total_rows=2520,
            gaps_count=5,
            outliers_count=2,
            stale_days=0,
            first_ts=datetime(2015, 1, 1, tzinfo=UTC),
            last_ts=datetime(2024, 12, 31, tzinfo=UTC),
        )
        quality_repo.write(report)

        latest = quality_repo.read_latest("AAPL")
        assert latest is not None
        assert latest.series_id == "AAPL"
        assert latest.quality_score == pytest.approx(report.quality_score, rel=1e-6)
        assert latest.total_rows == 2520

    def test_read_latest_for_unknown_returns_none(
        self, quality_repo: QualityReportRepository
    ) -> None:
        assert quality_repo.read_latest("DOES_NOT_EXIST") is None

    def test_multiple_writes_keeps_history(
        self, quality_repo: QualityReportRepository
    ) -> None:
        # Due report per la stessa serie a tempi diversi
        r1 = DataQualityReport(
            series_id="MSFT",
            series_kind="prices",
            quality_score=0.95,
            total_rows=100,
            evaluated_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
        r2 = DataQualityReport(
            series_id="MSFT",
            series_kind="prices",
            quality_score=0.82,
            total_rows=100,
            evaluated_at=datetime(2025, 6, 1, tzinfo=UTC),
        )
        quality_repo.write(r1)
        quality_repo.write(r2)

        # Il più recente deve essere r2
        latest = quality_repo.read_latest("MSFT")
        assert latest is not None
        assert latest.quality_score == pytest.approx(0.82, rel=1e-6)
