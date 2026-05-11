"""DataCleaner — orchestrator of the cleaning pipeline (Rule 14).

The data flow inside ``clean_ohlcv`` / ``clean_macro`` is:

    raw_df
        → drop duplicate timestamps     (uniqueness)
        → forward-fill short gaps       (completeness)
        → flag outliers                 (purity, NOT removed by default)
        → measure stale days            (freshness)
        → compute DataQualityReport     (Rule 26)
        → return CleaningResult(cleaned_df, report, outlier_mask)

The cleaner NEVER modifies the input; it returns a fresh copy. Caller
decides whether to drop or keep flagged outliers.

Rule 14: this module runs BEFORE Pandera validation.
Rule 26: every series produces a DataQualityReport.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pandas as pd
import yaml

from engine.market_data.cleaning.gap_filler import (
    count_gaps_business_days,
    forward_fill_short_gaps,
)
from engine.market_data.cleaning.outlier_detector import (
    detect_outliers_iqr,
    detect_outliers_zscore,
)
from engine.market_data.cleaning.stale_detector import (
    count_consecutive_repeats,
    count_stale_days,
)
from shared.constants import CONFIG_DIR
from shared.db.quality import DataQualityReport, QualityScoringConfig, load_quality_config
from shared.exceptions import DataCleaningError
from shared.logger import get_logger
from shared.metrics import metrics

if TYPE_CHECKING:
    from pathlib import Path

__version__ = "6.0.0"

__all__ = ["CleaningResult", "DataCleaner"]

log = get_logger(__name__)

_CONFIG_PATH = CONFIG_DIR / "data_quality.yaml"


# ═══════════════════════════════════════════════════════════════════════════
# Result type
# ═══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class CleaningResult:
    """Outcome of a cleaning run."""

    cleaned_df: pd.DataFrame
    report: DataQualityReport
    outlier_mask: pd.Series  # boolean, same index as cleaned_df


# ═══════════════════════════════════════════════════════════════════════════
# DataCleaner
# ═══════════════════════════════════════════════════════════════════════════
class DataCleaner:
    """Orchestrates the per-series cleaning pipeline.

    A single instance is configuration-bound: one set of thresholds/weights
    applies to all series it processes. Build a new instance with custom
    config when needed.
    """

    def __init__(
        self,
        scoring_config: QualityScoringConfig | None = None,
        config_path: Path = _CONFIG_PATH,
    ) -> None:
        self._scoring = scoring_config or load_quality_config(config_path)
        self._cleaning_cfg = self._load_cleaning_config(config_path)

    # ─── Config loader ──────────────────────────────────────────────────
    @staticmethod
    def _load_cleaning_config(path: Path) -> dict[str, dict[str, Any]]:
        """Load cleaning thresholds (outlier method, gap settings, stale).

        Values are kept as ``Any`` because YAML can yield mixed scalar
        types (str, int, float, bool); call sites cast to the expected
        Python type at the point of use.
        """
        if not path.exists():
            return _default_cleaning_config()
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return {
            "outlier": dict(raw.get("outlier_detection", {})),
            "stale": dict(raw.get("stale_detection", {})),
            "gap": dict(raw.get("gap_filling", {})),
        }

    # ─── OHLCV pipeline ────────────────────────────────────────────────
    def clean_ohlcv(
        self,
        df: pd.DataFrame,
        ticker: str,
    ) -> CleaningResult:
        """Apply the full cleaning pipeline to an OHLCV DataFrame.

        Args:
            df: Raw OHLCV DataFrame (must have ``ts``, ``close`` columns
                at minimum).
            ticker: Series identifier used in the report.
        """
        if df.empty:
            return self._empty_result(ticker, "prices")
        self._assert_required_columns(df, ["ts", "close"])

        with metrics.timer("data_cleaner_ohlcv_ms"):
            # 1. Dedup su timestamp (idempotenza upstream)
            deduped, dup_count = self._drop_duplicate_timestamps(df, ts_col="ts")

            # 2. Sort + forward-fill di gap brevi (completeness)
            gap_cfg = self._cleaning_cfg.get("gap", {})
            max_gap = int(gap_cfg.get("max_gap_days", 7))
            filled_df, _ = forward_fill_short_gaps(
                deduped, ts_col="ts", max_gap_days=max_gap,
                columns=["open", "high", "low", "close", "volume", "adj_close"],
            )
            gaps_count = count_gaps_business_days(filled_df["ts"])

            # 3. Outlier detection sui rendimenti del close (più stabili dei prezzi)
            outlier_mask = self._detect_outliers_on_returns(filled_df["close"])
            outliers_count = int(outlier_mask.sum())

            # 4. Stale detection
            stale_cfg = self._cleaning_cfg.get("stale", {})
            max_consecutive = int(stale_cfg.get("max_consecutive_same_value", 5))
            stuck_rows = count_consecutive_repeats(filled_df["close"], max_consecutive)
            stale_days = count_stale_days(filled_df["ts"])

            # 5. Quality report
            report = DataQualityReport.compute(
                series_id=ticker,
                series_kind="prices",
                total_rows=len(filled_df),
                gaps_count=gaps_count,
                outliers_count=outliers_count,
                stale_days=stale_days,
                duplicates_count=dup_count + stuck_rows,
                first_ts=filled_df["ts"].min().to_pydatetime() if len(filled_df) else None,
                last_ts=filled_df["ts"].max().to_pydatetime() if len(filled_df) else None,
                config=self._scoring,
            )

        log.info(
            "cleaner.ohlcv_done",
            ticker=ticker,
            rows=len(filled_df),
            score=round(report.quality_score, 3),
        )
        return CleaningResult(
            cleaned_df=filled_df.reset_index(drop=True),
            report=report,
            outlier_mask=outlier_mask.reset_index(drop=True),
        )

    # ─── Macro pipeline ────────────────────────────────────────────────
    def clean_macro(
        self,
        df: pd.DataFrame,
        series_id: str,
    ) -> CleaningResult:
        """Apply the full cleaning pipeline to a macro time-series.

        Differences vs OHLCV:
          · macro often has scheduled NaN (data not released yet)
          · cadence is monthly/quarterly, gap concept is fuzzier
          · outlier detection on raw values (not returns)
        """
        if df.empty:
            return self._empty_result(series_id, "macro")
        self._assert_required_columns(df, ["ts", "value"])

        with metrics.timer("data_cleaner_macro_ms"):
            deduped, dup_count = self._drop_duplicate_timestamps(df, ts_col="ts")
            sorted_df = deduped.sort_values("ts").reset_index(drop=True)

            # Outlier sui valori grezzi (i livelli macro sono più stabili dei prezzi)
            outlier_mask = self._detect_outliers_on_values(sorted_df["value"])
            outliers_count = int(outlier_mask.sum())

            # I NaN nei dati macro sono "gap" (FRED li espone come ".")
            gaps_count = int(sorted_df["value"].isna().sum())

            stale_cfg = self._cleaning_cfg.get("stale", {})
            max_consecutive = int(stale_cfg.get("max_consecutive_same_value", 5))
            stuck_rows = count_consecutive_repeats(
                sorted_df["value"].dropna(), max_consecutive
            )
            stale_days = count_stale_days(sorted_df["ts"])

            report = DataQualityReport.compute(
                series_id=series_id,
                series_kind="macro",
                total_rows=len(sorted_df),
                gaps_count=gaps_count,
                outliers_count=outliers_count,
                stale_days=stale_days,
                duplicates_count=dup_count + stuck_rows,
                first_ts=sorted_df["ts"].min().to_pydatetime() if len(sorted_df) else None,
                last_ts=sorted_df["ts"].max().to_pydatetime() if len(sorted_df) else None,
                config=self._scoring,
            )

        log.info(
            "cleaner.macro_done",
            series_id=series_id,
            rows=len(sorted_df),
            score=round(report.quality_score, 3),
        )
        return CleaningResult(
            cleaned_df=sorted_df,
            report=report,
            outlier_mask=outlier_mask.reset_index(drop=True),
        )

    # ─── Internals ──────────────────────────────────────────────────────
    @staticmethod
    def _assert_required_columns(df: pd.DataFrame, cols: list[str]) -> None:
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise DataCleaningError(
                f"Required column(s) missing for cleaning: {missing}"
            )

    @staticmethod
    def _drop_duplicate_timestamps(
        df: pd.DataFrame, ts_col: str
    ) -> tuple[pd.DataFrame, int]:
        """Remove duplicates keeping the LAST observation per timestamp."""
        n_before = len(df)
        # Keep="last" perché spesso i feed inviano correzioni in ritardo:
        # l'ultima copia per quel ts è la più aggiornata
        deduped = df.drop_duplicates(subset=[ts_col], keep="last").copy()
        n_dropped = n_before - len(deduped)
        return deduped, n_dropped

    def _detect_outliers_on_returns(self, prices: pd.Series) -> pd.Series:
        """Outlier detection on log-returns of a price series."""
        # Usiamo i log-returns: più simmetrici e stabili dei prezzi assoluti
        import numpy as np

        # Protezione: prezzi <= 0 producono -inf/NaN nel log
        safe_prices = prices.where(prices > 0)
        log_returns = np.log(safe_prices / safe_prices.shift(1))

        return self._dispatch_outlier(log_returns).reindex(prices.index, fill_value=False)

    def _detect_outliers_on_values(self, values: pd.Series) -> pd.Series:
        """Outlier detection on raw values (used for macro)."""
        return self._dispatch_outlier(values)

    def _dispatch_outlier(self, series: pd.Series) -> pd.Series:
        """Pick the configured outlier method and run it."""
        cfg = self._cleaning_cfg.get("outlier", {})
        method = str(cfg.get("method", "zscore")).lower()
        if method == "iqr":
            return detect_outliers_iqr(
                series, multiplier=float(cfg.get("iqr_multiplier", 3.0))
            )
        # Default: zscore (rolling se serie sufficientemente lunga)
        return detect_outliers_zscore(
            series,
            threshold=float(cfg.get("zscore_threshold", 4.0)),
            rolling_window=int(cfg.get("rolling_window", 30)),
        )

    @staticmethod
    def _empty_result(series_id: str, kind: str) -> CleaningResult:
        report = DataQualityReport.compute(
            series_id=series_id,
            series_kind=kind,
            total_rows=0,
        )
        return CleaningResult(
            cleaned_df=pd.DataFrame(),
            report=report,
            outlier_mask=pd.Series([], dtype=bool),
        )


def _default_cleaning_config() -> dict[str, dict[str, Any]]:
    """Hard-coded defaults if data_quality.yaml is missing."""
    return {
        "outlier": {
            "method": "zscore",
            "zscore_threshold": 4.0,
            "iqr_multiplier": 3.0,
            "rolling_window": 30,
        },
        "stale": {"max_consecutive_same_value": 5, "max_age_days": 5},
        "gap": {"method": "ffill", "max_gap_days": 7, "preserve_weekends": True},
    }
