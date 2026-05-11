"""BaseFetcher v6 — orchestrator of the Rule-12 pipeline.

Every external data source MUST inherit from one of the abstract bases
defined here (BaseOhlcvFetcher / BaseMacroFetcher) and implement only
the ``_fetch_raw_*`` method that pulls raw data from the provider.

The base class enforces the SACRED ORDER (Rule 12):

    fetch_raw → clean → validate → duckdb_write → cache → return

No subclass can bypass any step. The pipeline integrates:
  · RateLimitManager (Rule 28) — call .acquire(source) before fetch
  · DataCleaner (Rule 14)      — clean BEFORE Pandera validation
  · DataQualityReport (Rule 26) — computed and persisted on every fetch
  · DualWriter                 — DuckDB write + L1 cache update
  · ErrorBudget                — record success/failure for SLA tracking
"""
from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from engine.market_data.cleaning import CleaningResult, DataCleaner
from shared.db.dual_writer import DualWriter, DualWriteResult, get_dual_writer
from shared.db.quality import (
    DataQualityReport,
    QualityReportRepository,
    get_quality_repo,
)
from shared.error_budget import error_budget
from shared.exceptions import DataError, FetchError
from shared.logger import get_logger
from shared.metrics import metrics
from shared.rate_limit_manager import RateLimitManager, get_rate_limiter
from shared.types import DataSource, TimeFrame

if TYPE_CHECKING:
    from datetime import datetime

    import pandas as pd

__version__ = "6.0.0"

__all__ = [
    "BaseMacroFetcher",
    "BaseOhlcvFetcher",
    "FetchOutcome",
]

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Result type
# ═══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class FetchOutcome:
    """Final outcome of a Rule-12 pipeline run.

    Attributes:
        cleaned_df: The DataFrame after cleaning (post-Pandera validation).
        report: DataQualityReport produced and persisted.
        write_result: DuckDB + cache write result.
        is_acceptable_critical: True if quality_score >= 0.5 (Rule 26).
    """

    cleaned_df: pd.DataFrame
    report: DataQualityReport
    write_result: DualWriteResult
    is_acceptable_critical: bool


# ═══════════════════════════════════════════════════════════════════════════
# Common base — shared infrastructure for every fetcher
# ═══════════════════════════════════════════════════════════════════════════
class _PipelineBase:
    """Internal mixin holding the shared dependencies and helpers.

    Not abstract on its own — concrete subclasses (BaseOhlcvFetcher /
    BaseMacroFetcher) declare the abstract fetch methods.
    """

    def __init__(
        self,
        source: DataSource | str,
        rate_limiter: RateLimitManager | None = None,
        cleaner: DataCleaner | None = None,
        dual_writer: DualWriter | None = None,
        quality_repo: QualityReportRepository | None = None,
    ) -> None:
        # source come stringa per coerenza con la chiave in config/rate_limits.yaml
        self._source: str = source.value if isinstance(source, DataSource) else str(source)
        self._rate_limiter = rate_limiter or get_rate_limiter()
        self._cleaner = cleaner or DataCleaner()
        self._dual_writer = dual_writer or get_dual_writer()
        self._quality_repo = quality_repo or get_quality_repo()

    @property
    def source(self) -> str:
        """Identifier used both in logs and as RateLimitManager source key."""
        return self._source

    # ─── Helpers shared between OHLCV and macro pipelines ───────────────
    async def _acquire_rate_limit(self) -> None:
        """Wait for the rate limit budget. Logs and re-raises on exhaustion."""
        try:
            await self._rate_limiter.acquire(self._source)
        except Exception as exc:
            error_budget.record_error()
            metrics.inc("fetch_errors_total", source=self._source, kind="rate_limit")
            raise FetchError(source=self._source, detail=f"rate limit: {exc}") from exc

    def _persist_quality_report(self, report: DataQualityReport) -> None:
        """Persist report and emit warnings if score is below threshold."""
        try:
            self._quality_repo.write(report)
        except DataError as exc:
            # Errore di persistenza del report non blocca la pipeline:
            # il dato è già nel DB, è solo la metrica di qualità a perdersi
            log.warning(
                "fetcher.quality_persist_failed",
                source=self._source,
                series_id=report.series_id,
                error=str(exc),
            )

        if not report.is_acceptable_for_critical():
            log.warning(
                "fetcher.low_quality",
                source=self._source,
                series_id=report.series_id,
                score=round(report.quality_score, 3),
            )


# ═══════════════════════════════════════════════════════════════════════════
# OHLCV abstract fetcher
# ═══════════════════════════════════════════════════════════════════════════
class BaseOhlcvFetcher(_PipelineBase):
    """Abstract base for OHLCV (price bar) fetchers.

    Subclasses MUST implement ``_fetch_raw_ohlcv`` returning a raw DataFrame
    with the columns ``ts, open, high, low, close, volume`` (plus optional
    ``adj_close``). All OHLCV cleaning + validation + persistence is handled
    here.
    """

    @abstractmethod
    async def _fetch_raw_ohlcv(
        self,
        ticker: str,
        exchange: str,
        timeframe: TimeFrame,
        start: datetime | None,
        end: datetime | None,
    ) -> pd.DataFrame:
        """Fetch raw bars from the upstream API.

        Implementations should NOT clean, validate, or persist — those
        steps are handled by the base class.
        """

    async def fetch(
        self,
        ticker: str,
        exchange: str,
        timeframe: TimeFrame = TimeFrame.D1,
        start: datetime | None = None,
        end: datetime | None = None,
        currency: str = "USD",
    ) -> FetchOutcome:
        """Run the full Rule-12 pipeline for a single OHLCV series.

        Order is INVARIABLE: rate-limit → fetch → clean → validate
        → DuckDB write + cache → quality report persist → return.
        """
        # Pipeline timing globale per metrics
        with metrics.timer("pipeline_duration_ms", stage="fetch_ohlcv", source=self._source):
            # 1. Rate limit (Regola 28) — gate prima della rete
            await self._acquire_rate_limit()

            # 2. fetch_raw (delegato alla sottoclasse)
            raw_df = await self._fetch_raw(ticker, exchange, timeframe, start, end)

            # 3. clean (Regola 14)
            cleaning: CleaningResult = self._cleaner.clean_ohlcv(raw_df, ticker=ticker)

            # 4. duckdb_write + cache (Regola 12) — repository valida con Pandera
            try:
                write_result = self._dual_writer.write_prices(
                    ticker=ticker,
                    exchange=exchange,
                    timeframe=timeframe,
                    df=cleaning.cleaned_df,
                    source=self._source,
                    currency=currency,
                )
            except DataError as exc:
                error_budget.record_error()
                metrics.inc("fetch_errors_total", source=self._source, kind="write")
                raise FetchError(source=self._source, detail=f"write failed: {exc}") from exc

            # 5. quality report (Regola 26) — sempre persistito
            self._persist_quality_report(cleaning.report)

        # 6. Pipeline completata con successo: budget + return outcome
        error_budget.record_success()
        log.info(
            "fetcher.ohlcv_pipeline_done",
            source=self._source,
            ticker=ticker,
            rows=write_result.rows_written,
            score=round(cleaning.report.quality_score, 3),
        )
        return FetchOutcome(
            cleaned_df=cleaning.cleaned_df,
            report=cleaning.report,
            write_result=write_result,
            is_acceptable_critical=cleaning.report.is_acceptable_for_critical(),
        )

    # ─── Internal: fetch_raw wrapper with error tracking ────────────────
    async def _fetch_raw(
        self,
        ticker: str,
        exchange: str,
        timeframe: TimeFrame,
        start: datetime | None,
        end: datetime | None,
    ) -> pd.DataFrame:
        """Wrap subclass's ``_fetch_raw_ohlcv`` with metrics + error budget."""
        try:
            with metrics.timer("fetch_latency_ms", source=self._source, kind="ohlcv"):
                df = await self._fetch_raw_ohlcv(ticker, exchange, timeframe, start, end)
            metrics.inc("fetch_success_total", source=self._source, kind="ohlcv")
            return df
        except FetchError:
            # Già contabilizzato a livello inferiore; rilancia
            error_budget.record_error()
            raise
        except Exception as exc:
            error_budget.record_error()
            metrics.inc("fetch_errors_total", source=self._source, kind="fetch_raw")
            raise FetchError(
                source=self._source, detail=f"raw fetch failed: {exc}"
            ) from exc


# ═══════════════════════════════════════════════════════════════════════════
# Macro abstract fetcher
# ═══════════════════════════════════════════════════════════════════════════
class BaseMacroFetcher(_PipelineBase):
    """Abstract base for macro time-series fetchers (FRED, ECB, BLS, ...).

    Subclasses MUST implement ``_fetch_raw_macro`` returning a DataFrame
    with the columns ``ts, value``. The base class handles everything else.
    """

    @abstractmethod
    async def _fetch_raw_macro(
        self,
        series_id: str,
        start: datetime | None,
        end: datetime | None,
    ) -> pd.DataFrame:
        """Fetch raw macro observations from the upstream API."""

    async def fetch(
        self,
        series_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        unit: str | None = None,
        frequency: str | None = None,
    ) -> FetchOutcome:
        """Run the full Rule-12 pipeline for a single macro series."""
        with metrics.timer("pipeline_duration_ms", stage="fetch_macro", source=self._source):
            await self._acquire_rate_limit()
            raw_df = await self._fetch_raw(series_id, start, end)
            cleaning = self._cleaner.clean_macro(raw_df, series_id=series_id)

            try:
                write_result = self._dual_writer.write_macro(
                    series_id=series_id,
                    df=cleaning.cleaned_df,
                    source=self._source,
                    unit=unit,
                    frequency=frequency,
                )
            except DataError as exc:
                error_budget.record_error()
                metrics.inc("fetch_errors_total", source=self._source, kind="write")
                raise FetchError(source=self._source, detail=f"write failed: {exc}") from exc

            self._persist_quality_report(cleaning.report)

        error_budget.record_success()
        log.info(
            "fetcher.macro_pipeline_done",
            source=self._source,
            series_id=series_id,
            rows=write_result.rows_written,
            score=round(cleaning.report.quality_score, 3),
        )
        return FetchOutcome(
            cleaned_df=cleaning.cleaned_df,
            report=cleaning.report,
            write_result=write_result,
            is_acceptable_critical=cleaning.report.is_acceptable_for_critical(),
        )

    async def _fetch_raw(
        self,
        series_id: str,
        start: datetime | None,
        end: datetime | None,
    ) -> pd.DataFrame:
        """Wrap subclass's ``_fetch_raw_macro`` with metrics + error budget."""
        try:
            with metrics.timer("fetch_latency_ms", source=self._source, kind="macro"):
                df = await self._fetch_raw_macro(series_id, start, end)
            metrics.inc("fetch_success_total", source=self._source, kind="macro")
            return df
        except FetchError:
            error_budget.record_error()
            raise
        except Exception as exc:
            error_budget.record_error()
            metrics.inc("fetch_errors_total", source=self._source, kind="fetch_raw")
            raise FetchError(
                source=self._source, detail=f"raw fetch failed: {exc}"
            ) from exc
