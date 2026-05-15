"""MarketAI Scheduler v2.2 — Orchestratore.

Regola 2 (SRP): contiene SOLO imports, _JOB_REGISTRY, monitor, main().
Logica dei job nei moduli separati (Settimana 7 refactoring):
  · scripts/scheduler_jobs_data.py     — fetch dati
  · scripts/scheduler_jobs_analysis.py — analisi e segnali

Ordine esecuzione settimanale (lunedì):
  06:45 → surprise_consensus_load → 07:00 → macro_fred
  → 07:30 → av_fundamentals → 08:00 → surprise_engine_v2

Ordine intraday lun-ven ogni 4h:
  :00 prices → :05 futures → :15 curve+credit → :30 vix → :45 pipeline

ANTI-REGRESSIONE: scheduler_jobs_data/analysis importano scheduler_utils
come PRIMO import per garantire sys.path configurato prima dei moduli app.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from shared.error_budget import error_budget
from shared.feature_flags import is_enabled
from shared.logger import configure_logging, get_logger
from scripts.scheduler_jobs_data import (
    _job_market_prices, _job_futures_prices, _job_macro_fred,
    _job_claims_inflation, _job_yield_curve, _job_credit_spreads,
    _job_labour_jolts, _job_labour_claims_cycle, _job_labour_payroll,
)
from scripts.scheduler_jobs_analysis import (
    _job_vix_strategy, _job_analysis_pipeline,
    _job_edgar_fundamentals, _job_av_fundamentals,
    _job_surprise_consensus_loader, _job_surprise_engine_v2,
    _job_labour_regime, _job_labour_forecast,
    _job_backup, _job_retention,
)

log = get_logger("scheduler")
__version__ = "2.2.0"


# ─── Job Registry ─────────────────────────────────────────────────────────────

_JOB_REGISTRY: list[dict] = [
    # ── Intraday (lun-ven, ogni 4h) ───────────────────────────────────────
    {"id": "market_prices",     "flag": "market_data_refresh",
     "trigger": CronTrigger(day_of_week="mon-fri", hour="8,12,16,20", minute=0),
     "fn": _job_market_prices,     "name": "Market prices OHLCV"},

    {"id": "futures_prices",    "flag": "futures_analysis",
     "trigger": CronTrigger(day_of_week="mon-fri", hour="8,12,16,20", minute=5),
     "fn": _job_futures_prices,    "name": "Futures + roll/basis/OI"},

    {"id": "yield_curve",       "flag": "market_data_refresh",
     "trigger": CronTrigger(day_of_week="mon-fri", hour="8,12,16,20", minute=15),
     "fn": _job_yield_curve,       "name": "Yield curve snapshot"},

    {"id": "credit_spreads",    "flag": "hy_credit_spread",
     "trigger": CronTrigger(day_of_week="mon-fri", hour="8,12,16,20", minute=15),
     "fn": _job_credit_spreads,    "name": "Credit spreads HY/IG"},

    {"id": "vix_strategy",      "flag": "vix_based_analysis",
     "trigger": CronTrigger(day_of_week="mon-fri", hour="8,12,16,20", minute=30),
     "fn": _job_vix_strategy,      "name": "VIX strategy regime-aware"},

    {"id": "analysis_pipeline", "flag": "analysis_pipeline_scheduled",
     "trigger": CronTrigger(day_of_week="mon-fri", hour="8,12,16,20", minute=45),
     "fn": _job_analysis_pipeline, "name": "Analysis pipeline + CompositeSignal"},

    # ── Giornalieri ───────────────────────────────────────────────────────
    {"id": "macro_fred",        "flag": "market_data_refresh",
     "trigger": CronTrigger(day_of_week="mon-fri", hour=7, minute=0),
     "fn": _job_macro_fred,        "name": "FRED macro 28 serie (07:00)"},

    {"id": "claims_cross",      "flag": "claims_inflation_cross",
     "trigger": CronTrigger(day_of_week="thu", hour=16, minute=30),
     "fn": _job_claims_inflation,  "name": "Claims/Inflation cross (giovedì 16:30)"},

    # ── Settimanali fondamentali (Roadmap v3.0 Sett.1) ─────────────────────
    {"id": "edgar_fundamentals", "flag": "edgar_fundamentals_scheduler",
     "trigger": CronTrigger(day_of_week="sun", hour=6, minute=0),
     "fn": _job_edgar_fundamentals,
     "name": "EDGAR fundamentals income+balance (domenica 06:00)"},

    {"id": "av_fundamentals",   "flag": "av_fundamentals_scheduler",
     "trigger": CronTrigger(day_of_week="mon", hour=7, minute=30),
     "fn": _job_av_fundamentals,   "name": "AV P/E EV/EBITDA (lunedì 07:30)"},

    # ── Surprise Engine v2 (Roadmap v3.0 Sett.6) ──────────────────────────
    {"id": "surprise_consensus_load", "flag": "surprise_consensus_loader",
     "trigger": CronTrigger(day_of_week="mon", hour=6, minute=45),
     "fn": _job_surprise_consensus_loader,
     "name": "Surprise consensus YAML+FRED (lunedì 06:45)"},

    {"id": "surprise_engine_v2", "flag": "surprise_scheduler",
     "trigger": CronTrigger(day_of_week="mon", hour=8, minute=0),
     "fn": _job_surprise_engine_v2,
     "name": "Surprise Engine v2 pipeline (lunedì 08:00)"},

    # ── Labour Market (Roadmap v4 Blocco 1) ───────────────────────────────
    {"id": "labour_jolts",       "flag": "labour_market_fetcher",
     "trigger": CronTrigger(day_of_week="wed", hour=17, minute=0),
     "fn": _job_labour_jolts,
     "name": "JOLTS mensile da FRED (mercoledì 17:00)"},

    {"id": "labour_claims",      "flag": "labour_market_fetcher",
     "trigger": CronTrigger(day_of_week="thu", hour=8, minute=30),
     "fn": _job_labour_claims_cycle,
     "name": "Initial Claims ciclo settimanale (giovedì 08:30)"},

    {"id": "labour_payroll",     "flag": "labour_market_fetcher",
     "trigger": CronTrigger(day_of_week="fri", hour=8, minute=30),
     "fn": _job_labour_payroll,
     "name": "NFP settoriale PayrollDecomposer (venerdì 08:30)"},

    {"id": "labour_regime",      "flag": "labour_market_scheduler",
     "trigger": CronTrigger(day_of_week="fri", hour=18, minute=0),
     "fn": _job_labour_regime,
     "name": "Labour Regime Classifier (venerdì 18:00)"},

    {"id": "labour_forecast",    "flag": "labour_market_forecasting",
     "trigger": CronTrigger(day_of_week="mon", hour=10, minute=0),
     "fn": _job_labour_forecast,
     "name": "Labour Forecast ARIMA+Ridge 1M/3M/6M (lunedì 10:00)"},

    # ── Manutenzione ──────────────────────────────────────────────────────
    {"id": "daily_backup",      "flag": "auto_backup_daily",
     "trigger": CronTrigger(hour=2, minute=0),
     "fn": _job_backup,            "name": "Daily backup DuckDB"},

    {"id": "monthly_retention", "flag": "auto_retention_cleanup",
     "trigger": CronTrigger(day=1, hour=3, minute=0),
     "fn": _job_retention,         "name": "Monthly retention cleanup"},
]


# ─── Error Budget Monitor (Regola 30) ─────────────────────────────────────────

def _check_error_budget() -> None:
    """Error rate > 10% negli ultimi 5 min → log CRITICAL + raccomanda sospensione."""
    try:
        rate = error_budget.error_rate_5min()
        if rate > 0.10:
            log.error(
                "scheduler.error_budget.exceeded",
                error_rate_5min=round(rate, 3),
                action="auto-suspend recommended",
            )
    except Exception as exc:
        log.warning("scheduler.error_budget_check_failed", error=str(exc)[:80])


# ─── Main ─────────────────────────────────────────────────────────────────────

def main(dry_run: bool = False) -> int:
    configure_logging()
    scheduler = BlockingScheduler(timezone="UTC")
    registered = 0

    for job in _JOB_REGISTRY:
        flag = job.get("flag")
        if flag and not is_enabled(flag):
            log.debug("scheduler.job_flag_skip", job_id=job["id"], flag=flag)
            continue
        if dry_run:
            log.info("scheduler.dry_run", job_id=job["id"], name=job["name"])
        else:
            scheduler.add_job(
                job["fn"], trigger=job["trigger"],
                id=job["id"], name=job["name"], replace_existing=True,
            )
        log.info("scheduler.registered", job=job["id"])
        registered += 1

    if not dry_run:
        scheduler.add_job(
            _check_error_budget,
            trigger=CronTrigger(minute="*"),
            id="error_budget_monitor",
            replace_existing=True,
        )

    log.info("scheduler.ready", version=__version__,
             registered=registered, dry_run=dry_run)

    if dry_run:
        return 0
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("scheduler.stopped")
    return 0


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description=f"MarketAI Scheduler v{__version__}")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    sys.exit(main(dry_run=args.dry_run))
