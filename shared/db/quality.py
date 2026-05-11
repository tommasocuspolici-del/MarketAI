"""DataQualityReport — single source of truth for data-quality scoring (Rule 26).

Every time-series that enters the system must have an associated report.
Reports are persisted to the ``data_quality_reports`` DuckDB table (created
by migration 20260401_001_initial_schema).

The score in [0, 1] is a weighted mean of four orthogonal components:
  · completeness    — 1 - gaps_pct
  · outlier_purity  — 1 - outliers_pct
  · freshness       — 1 - stale_days/max_stale
  · uniqueness      — 1 - duplicates_pct

Weights configurable in config/data_quality.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import yaml

from shared.constants import CONFIG_DIR, MIN_QUALITY_SCORE_BACKTEST, MIN_QUALITY_SCORE_CRITICAL
from shared.db.duckdb_client import DuckDBClient, get_duckdb_client
from shared.exceptions import ConfigurationError, DataQualityError
from shared.logger import get_logger
from shared.metrics import metrics
from shared.types import now_utc

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

__version__ = "6.0.0"

__all__ = [
    "DataQualityReport",
    "QualityReportRepository",
    "QualityScoringConfig",
    "get_quality_repo",
    "load_quality_config",
]

log = get_logger(__name__)

_TABLE = "data_quality_reports"
_CONFIG_PATH = CONFIG_DIR / "data_quality.yaml"


# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class QualityScoringConfig:
    """Weights and thresholds for quality scoring."""

    weight_completeness: float
    weight_outlier_purity: float
    weight_freshness: float
    weight_uniqueness: float
    max_stale_days: int
    min_score_critical: float
    min_score_backtest: float
    warn_score: float

    def __post_init__(self) -> None:
        # Verifica pesi: somma deve essere ~1 (tolleranza per arrotondamenti YAML)
        total = (
            self.weight_completeness
            + self.weight_outlier_purity
            + self.weight_freshness
            + self.weight_uniqueness
        )
        if not 0.99 <= total <= 1.01:
            raise ConfigurationError(
                f"Quality score weights must sum to 1.0, got {total:.4f}"
            )


def load_quality_config(path: Path = _CONFIG_PATH) -> QualityScoringConfig:
    """Load the quality scoring config from YAML (with safe defaults)."""
    if not path.exists():
        log.warning("quality_config.missing", path=str(path))
        return _default_config()

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    weights = raw.get("score_weights", {})
    stale = raw.get("stale_detection", {})
    accept = raw.get("acceptance", {})

    return QualityScoringConfig(
        weight_completeness=float(weights.get("completeness", 0.35)),
        weight_outlier_purity=float(weights.get("outlier_purity", 0.30)),
        weight_freshness=float(weights.get("freshness", 0.20)),
        weight_uniqueness=float(weights.get("uniqueness", 0.15)),
        max_stale_days=int(stale.get("max_age_days", 5)),
        min_score_critical=float(accept.get("min_score_critical", MIN_QUALITY_SCORE_CRITICAL)),
        min_score_backtest=float(accept.get("min_score_backtest", MIN_QUALITY_SCORE_BACKTEST)),
        warn_score=float(accept.get("warn_score", 0.8)),
    )


def _default_config() -> QualityScoringConfig:
    """Hard-coded fallback used when config/data_quality.yaml is missing."""
    return QualityScoringConfig(
        weight_completeness=0.35,
        weight_outlier_purity=0.30,
        weight_freshness=0.20,
        weight_uniqueness=0.15,
        max_stale_days=5,
        min_score_critical=MIN_QUALITY_SCORE_CRITICAL,
        min_score_backtest=MIN_QUALITY_SCORE_BACKTEST,
        warn_score=0.8,
    )


# ═══════════════════════════════════════════════════════════════════════════
# DataQualityReport
# ═══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class DataQualityReport:
    """Quality assessment of a single time-series."""

    series_id: str
    series_kind: str           # "prices" | "macro" | "fundamentals" | "sentiment"
    quality_score: float       # [0.0, 1.0]
    total_rows: int
    gaps_count: int = 0
    gaps_pct: float = 0.0
    outliers_count: int = 0
    outliers_pct: float = 0.0
    stale_days: int = 0
    duplicates_count: int = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    notes: str = ""
    evaluated_at: datetime = field(default_factory=now_utc)

    # ─── Decisione: il dato è utilizzabile? ────────────────────────────
    def is_acceptable_for_critical(self, threshold: float = MIN_QUALITY_SCORE_CRITICAL) -> bool:
        """Whether the series is fit for critical calculations (Rule 26)."""
        return self.quality_score >= threshold

    def is_acceptable_for_backtest(self, threshold: float = MIN_QUALITY_SCORE_BACKTEST) -> bool:
        """Whether the series is fit for backtests (stricter)."""
        return self.quality_score >= threshold

    def assert_critical(self, threshold: float = MIN_QUALITY_SCORE_CRITICAL) -> None:
        """Raise DataQualityError if not acceptable for critical use."""
        if not self.is_acceptable_for_critical(threshold):
            raise DataQualityError(
                series_id=self.series_id,
                score=self.quality_score,
                minimum=threshold,
            )

    # ─── Score builder ─────────────────────────────────────────────────
    @classmethod
    def compute(
        cls,
        series_id: str,
        series_kind: str,
        total_rows: int,
        gaps_count: int = 0,
        outliers_count: int = 0,
        stale_days: int = 0,
        duplicates_count: int = 0,
        first_ts: datetime | None = None,
        last_ts: datetime | None = None,
        notes: str = "",
        config: QualityScoringConfig | None = None,
    ) -> DataQualityReport:
        """Build a report computing the weighted quality score."""
        cfg = config or load_quality_config()

        # Normalizzazione percentuali: protezione da divisione per zero
        denom = max(total_rows, 1)
        gaps_pct = gaps_count / denom
        outliers_pct = outliers_count / denom

        # Singoli sub-score in [0, 1] dove 1 = perfetto
        completeness = max(0.0, 1.0 - gaps_pct)
        outlier_purity = max(0.0, 1.0 - outliers_pct)
        freshness = max(0.0, 1.0 - min(1.0, stale_days / max(cfg.max_stale_days, 1)))
        duplicates_pct = duplicates_count / denom
        uniqueness = max(0.0, 1.0 - duplicates_pct)

        # Media ponderata
        score = (
            completeness * cfg.weight_completeness
            + outlier_purity * cfg.weight_outlier_purity
            + freshness * cfg.weight_freshness
            + uniqueness * cfg.weight_uniqueness
        )
        # Clip difensivo (non dovrebbe mai uscire dai limiti se i pesi sommano a 1)
        score = max(0.0, min(1.0, score))

        return cls(
            series_id=series_id,
            series_kind=series_kind,
            quality_score=score,
            total_rows=total_rows,
            gaps_count=gaps_count,
            gaps_pct=gaps_pct,
            outliers_count=outliers_count,
            outliers_pct=outliers_pct,
            stale_days=stale_days,
            duplicates_count=duplicates_count,
            first_ts=first_ts,
            last_ts=last_ts,
            notes=notes,
        )

    def to_dict(self) -> dict[str, Any]:
        """Plain dict suitable for JSON / logging."""
        return {
            "series_id": self.series_id,
            "series_kind": self.series_kind,
            "quality_score": self.quality_score,
            "total_rows": self.total_rows,
            "gaps_count": self.gaps_count,
            "gaps_pct": self.gaps_pct,
            "outliers_count": self.outliers_count,
            "outliers_pct": self.outliers_pct,
            "stale_days": self.stale_days,
            "duplicates_count": self.duplicates_count,
            "first_ts": self.first_ts.isoformat() if self.first_ts else None,
            "last_ts": self.last_ts.isoformat() if self.last_ts else None,
            "notes": self.notes,
            "evaluated_at": self.evaluated_at.isoformat(),
        }


# ═══════════════════════════════════════════════════════════════════════════
# Persistence
# ═══════════════════════════════════════════════════════════════════════════
class QualityReportRepository:
    """Persists DataQualityReport instances to DuckDB."""

    def __init__(self, client: DuckDBClient | None = None) -> None:
        self._client = client or get_duckdb_client()

    def write(self, report: DataQualityReport) -> None:
        """Insert a report into ``data_quality_reports``."""
        with metrics.timer("quality_report_write_ms"):
            self._client.execute(
                f"""
                INSERT INTO {_TABLE} (
                    series_id, series_kind, evaluated_at, quality_score,
                    gaps_count, gaps_pct, outliers_count, outliers_pct,
                    stale_days, total_rows, first_ts, last_ts, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    report.series_id,
                    report.series_kind,
                    report.evaluated_at,
                    report.quality_score,
                    report.gaps_count,
                    report.gaps_pct,
                    report.outliers_count,
                    report.outliers_pct,
                    report.stale_days,
                    report.total_rows,
                    report.first_ts,
                    report.last_ts,
                    report.notes,
                ],
            )
        # Gauge per dashboard di osservabilità
        metrics.set_gauge(
            "data_quality_score",
            report.quality_score,
            series=report.series_id,
        )
        log.info(
            "quality_report.written",
            series_id=report.series_id,
            score=round(report.quality_score, 3),
        )

    def read_latest(self, series_id: str) -> DataQualityReport | None:
        """Fetch the most recent report for a series, or None."""
        rows = self._client.query(
            f"""
            SELECT series_id, series_kind, quality_score, total_rows,
                   gaps_count, gaps_pct, outliers_count, outliers_pct,
                   stale_days, first_ts, last_ts, notes, evaluated_at
            FROM {_TABLE}
            WHERE series_id = ?
            ORDER BY evaluated_at DESC LIMIT 1
            """,
            [series_id],
        )
        if not rows:
            return None
        r = rows[0]
        return DataQualityReport(
            series_id=r[0],
            series_kind=r[1],
            quality_score=float(r[2]),
            total_rows=int(r[3]),
            gaps_count=int(r[4]),
            gaps_pct=float(r[5]),
            outliers_count=int(r[6]),
            outliers_pct=float(r[7]),
            stale_days=int(r[8]),
            first_ts=r[9],
            last_ts=r[10],
            notes=r[11] or "",
            evaluated_at=r[12],
        )


# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════
_INSTANCE: QualityReportRepository | None = None


def get_quality_repo() -> QualityReportRepository:
    """Return the process-wide QualityReportRepository singleton."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = QualityReportRepository()
    return _INSTANCE


def reset_quality_repo() -> None:
    """Reset singleton (tests only)."""
    global _INSTANCE
    _INSTANCE = None
