#!/usr/bin/env python3
"""Scheduler entry point.

Registers scheduled jobs:
  · Daily backup at 02:00
  · Monthly retention cleanup on day 1 at 03:00

Future phases will add:
  · Market data refresh (every 4h)
  · Analysis pipeline (every 4h trading days)
  · Sentiment aggregation (hourly)

Usage:
    python scripts/run_scheduler.py
    make scheduler
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: E402
from apscheduler.triggers.cron import CronTrigger  # noqa: E402

from shared.error_budget import error_budget  # noqa: E402
from shared.feature_flags import is_enabled  # noqa: E402
from shared.logger import configure_logging, get_logger  # noqa: E402

log = get_logger("scheduler")


def _job_backup() -> None:
    """Wrap backup invocation with error-budget tracking."""
    from shared.backup_manager import BackupManager
    from shared.exceptions import BackupError

    try:
        archive = BackupManager().run_backup()
        error_budget.record_success()
        log.info("scheduler.backup_done", path=str(archive))
    except BackupError as exc:
        error_budget.record_error()
        log.error("scheduler.backup_failed", error=str(exc))


def _job_retention() -> None:
    """Wrap retention invocation with error-budget tracking."""
    try:
        from scripts.duckdb_retention import main as retention_main

        retention_main()
        error_budget.record_success()
    except Exception as exc:
        error_budget.record_error()
        log.error("scheduler.retention_failed", error=str(exc))


def _check_error_budget() -> None:
    """Periodic check — auto-suspend if budget breached (Rule 30)."""
    if error_budget.is_tripped:
        status = error_budget.status()
        log.warning(
            "scheduler.error_budget_tripped",
            error_rate_pct=status.error_rate_pct,
            threshold_pct=status.threshold_pct,
        )


def main() -> int:
    configure_logging()
    scheduler = BlockingScheduler(timezone="UTC")

    # ─── Registrazione job condizionali sui feature flag ────────────────
    if is_enabled("auto_backup_daily"):
        scheduler.add_job(
            _job_backup,
            trigger=CronTrigger(hour=2, minute=0),
            id="daily_backup",
            name="Daily DuckDB + SQLite backup",
            replace_existing=True,
        )
        log.info("scheduler.registered", job="daily_backup")

    if is_enabled("auto_retention_cleanup"):
        scheduler.add_job(
            _job_retention,
            trigger=CronTrigger(day=1, hour=3, minute=0),
            id="monthly_retention",
            name="Monthly retention cleanup",
            replace_existing=True,
        )
        log.info("scheduler.registered", job="monthly_retention")

    # Error budget monitor ogni minuto
    scheduler.add_job(
        _check_error_budget,
        trigger=CronTrigger(minute="*"),
        id="error_budget_monitor",
        replace_existing=True,
    )

    log.info("scheduler.starting")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("scheduler.stopped")

    return 0


if __name__ == "__main__":
    # Avviabile anche come modulo: python -m scripts.run_scheduler
    sys.exit(main())
