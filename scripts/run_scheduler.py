#!/usr/bin/env python3
"""Scheduler v2.0 — Roadmap Unificata Settimana 2.

Versione DEFINITIVA: tutti i job Fix N1 + VIX + 25 Migliorie Engine.

Ordine di esecuzione per ogni run 4h (lun-ven):
  :00 → market_prices     (watched_tickers.yaml)
  :05 → futures_prices    (CL=F, GC=F, ES=F)
  :15 → yield_curve       (DGS2/10/3M + T10YIE)
  :15 → credit_spreads    (HY OAS + TED + NFCI)
  :30 → vix_strategy      (Z-Score regime-aware)
  :45 → analysis_pipeline (Composite Signal aggregato)

Job giornalieri:
  07:00 lun-ven  → macro_fred (28 serie FRED)
  giovedì 16:30  → claims_cross

Manutenzione:
  02:00 daily → backup
  03:00 day 1 → retention

Regola 29: tutti i job controllati da feature flag.
Regola 30: error_budget.record_error() su ogni eccezione.

Usage:
    python scripts/run_scheduler.py
    python scripts/run_scheduler.py --dry-run
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from shared.error_budget import error_budget
from shared.feature_flags import is_enabled
from shared.logger import configure_logging, get_logger

log = get_logger("scheduler")
__version__ = "2.0.0"


def _run_async(coro):
    """Esegui una coroutine da un contesto sincrono (APScheduler)."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


# ─── JOB: Market Prices (:00 ogni 4h lun-ven) ────────────────────────────

def _job_market_prices() -> None:
    """Fetcha OHLCV per tutti i ticker non-futures in watched_tickers.yaml."""
    t0 = time.monotonic()
    try:
        import yaml
        from engine.market_data.fetchers.yahoo_fetcher import YahooFetcher
        from shared.types import TimeFrame

        config_path = _PROJECT_ROOT / "config" / "watched_tickers.yaml"
        with config_path.open() as f:
            config = yaml.safe_load(f)

        fetcher = YahooFetcher()
        ticker_count = 0

        async def _fetch_all():
            nonlocal ticker_count
            for _cat, tickers in config.items():
                if not isinstance(tickers, list):
                    continue
                for entry in tickers:
                    if not isinstance(entry, dict):
                        continue
                    ticker = entry.get("ticker", "")
                    if ticker.endswith("=F"):  # futures gestiti separatamente
                        continue
                    try:
                        await fetcher.fetch(
                            ticker=ticker,
                            exchange=entry.get("exchange", "NYSE"),
                            timeframe=TimeFrame.D1,
                        )
                        ticker_count += 1
                    except Exception as exc:
                        log.warning("scheduler.prices.ticker_failed",
                                    ticker=ticker, error=str(exc)[:80])

        _run_async(_fetch_all())
        error_budget.record_success()
        log.info("scheduler.market_prices.done",
                 tickers=ticker_count, duration_ms=round((time.monotonic() - t0) * 1000))
    except Exception as exc:
        error_budget.record_error()
        log.error("scheduler.market_prices.failed", error=str(exc)[:200])


# ─── JOB: Futures Prices (:05 ogni 4h lun-ven) ───────────────────────────
# Settimana 5: fetch + analisi completa (roll + basis + OI + regime)

def _job_futures_prices() -> None:
    """Fetcha futures + calcola roll_yield, basis, OI → CommodityAnalysis."""
    t0 = time.monotonic()
    try:
        from engine.market_data.fetchers.futures_fetcher import FuturesFetcher
        from engine.futures_analysis import (
            RollAnalyzer, BasisAnalyzer,
            OpenInterestAnalyzer, CommodityRegimeClassifier,
        )
        from shared.db.duckdb_client import get_duckdb_client
        from shared.db.prices_repo import get_prices_repository

        db          = get_duckdb_client()
        prices_repo = get_prices_repository()

        # 1. Fetch OHLCV futures e persisti in futures_ohlcv
        fetcher = FuturesFetcher(duckdb_client=db)
        results = _run_async(fetcher.fetch_all(days=60))
        rows = sum(r.get("rows_written", 0) for r in results)

        # 2. Analisi completa per ogni ticker fetchato
        roll_a  = RollAnalyzer(duckdb=db)
        basis_a = BasisAnalyzer(duckdb=db, prices_repo=prices_repo)
        oi_a    = OpenInterestAnalyzer(duckdb=db)
        classifier = CommodityRegimeClassifier(
            roll_analyzer=roll_a,
            basis_analyzer=basis_a,
            oi_analyzer=oi_a,
        )

        analyses = []
        for r in results:
            ticker = r.get("ticker", "")
            try:
                analysis = classifier.classify(ticker)
                analyses.append(analysis)
                log.info(
                    "scheduler.futures_analysis.ticker_done",
                    ticker=ticker,
                    regime=analysis.regime.value,
                    score=round(analysis.score, 3),
                )
            except Exception as exc:
                log.warning("scheduler.futures_analysis.ticker_failed",
                            ticker=ticker, error=str(exc)[:80])

        error_budget.record_success()
        log.info(
            "scheduler.futures_prices.done",
            fetched=len(results), rows_written=rows,
            analyses=len(analyses),
            duration_ms=round((time.monotonic() - t0) * 1000),
        )
    except Exception as exc:
        error_budget.record_error()
        log.error("scheduler.futures_prices.failed", error=str(exc)[:200])


# ─── JOB: Macro FRED (07:00 lun-ven) ─────────────────────────────────────

def _job_macro_fred() -> None:
    """Scarica tutte le serie FRED da macro_extended.yaml."""
    t0 = time.monotonic()
    try:
        import yaml
        from engine.market_data.fetchers.fred_fetcher import FREDFetcher
        from shared.db.macro_repo import get_macro_repository

        with (_PROJECT_ROOT / "config" / "macro_extended.yaml").open() as f:
            config = yaml.safe_load(f)

        fetcher = FREDFetcher()
        repo = get_macro_repository()
        series_count = rows_total = 0

        async def _fetch_all():
            nonlocal series_count, rows_total
            for _cat, series_list in config.items():
                if not isinstance(series_list, list):
                    continue
                for entry in series_list:
                    sid = entry.get("id", "")
                    if not sid:
                        continue
                    try:
                        outcome = await fetcher.fetch(series_id=sid)
                        if outcome and not outcome.cleaned_df.empty:
                            rows_total += repo.write_macro_series(
                                series_id=sid, df=outcome.cleaned_df,
                                source="fred", frequency=entry.get("freq"),
                            )
                            series_count += 1
                    except Exception as exc:
                        log.warning("scheduler.macro_fred.failed",
                                    series_id=sid, error=str(exc)[:80])

        _run_async(_fetch_all())
        error_budget.record_success()
        log.info("scheduler.macro_fred.done",
                 series=series_count, rows=rows_total,
                 duration_ms=round((time.monotonic() - t0) * 1000))
    except Exception as exc:
        error_budget.record_error()
        log.error("scheduler.macro_fred.failed", error=str(exc)[:200])


# ─── JOB: Claims/Inflation Cross (giovedì 16:30) ─────────────────────────

def _job_claims_inflation() -> None:
    """Segnale Claims/Inflation — giovedì è il giorno di uscita del dato."""
    t0 = time.monotonic()
    try:
        from datetime import datetime, timezone
        from shared.db.duckdb_client import get_duckdb_client
        from shared.db.macro_repo import get_macro_repository

        repo = get_macro_repository()
        db = get_duckdb_client()

        icsa_df = repo.read_macro("ICSA")
        cpi_df  = repo.read_macro("CPIAUCSL")
        if icsa_df.empty or cpi_df.empty:
            log.warning("scheduler.claims_cross.no_data")
            return

        icsa_vals = icsa_df["value"].dropna()
        if len(icsa_vals) < 4:
            return

        icsa_4wk_ma = float(icsa_vals.tail(4).mean())
        icsa_yoy = None
        if len(icsa_vals) >= 52:
            prev = float(icsa_vals.iloc[-53])
            if prev > 0:
                icsa_yoy = (icsa_4wk_ma - prev) / prev

        cpi_yoy = float(cpi_df["value"].dropna().iloc[-1])

        goldilocks  = icsa_4wk_ma < 300_000 and cpi_yoy < 3.5
        stagflation = (icsa_yoy or 0) > 0.10 and cpi_yoy > 3.0
        overheating = icsa_4wk_ma < 250_000 and cpi_yoy > 4.0
        recession   = (icsa_yoy or 0) > 0.20 and cpi_yoy < 2.5

        if stagflation:   regime, score = "stagflation", -1.0
        elif goldilocks:  regime, score = "goldilocks",   0.8
        elif overheating: regime, score = "overheating", -0.3
        elif recession:   regime, score = "recession",   -0.6
        else:             regime, score = "neutral",      0.0

        now = datetime.now(timezone.utc)
        db.execute(
            "INSERT OR REPLACE INTO claims_inflation_signals "
            "(computed_at, icsa_4wk_ma, icsa_yoy_change_pct, cpi_yoy, "
            "stagflation_signal, goldilocks_signal, overheating_signal, "
            "recession_watch, regime_label, regime_score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [now, icsa_4wk_ma, icsa_yoy, cpi_yoy,
             stagflation, goldilocks, overheating, recession, regime, score],
        )
        error_budget.record_success()
        log.info("scheduler.claims_cross.done", regime=regime, score=score,
                 duration_ms=round((time.monotonic() - t0) * 1000))
    except Exception as exc:
        error_budget.record_error()
        log.error("scheduler.claims_cross.failed", error=str(exc)[:200])


# ─── JOB: Yield Curve (:15 ogni 4h lun-ven) ──────────────────────────────

def _job_yield_curve() -> None:
    """Snapshot curva yield + Estrella-Mishkin recession probability."""
    t0 = time.monotonic()
    try:
        from datetime import date, datetime, timezone
        from scipy.stats import norm
        from shared.db.duckdb_client import get_duckdb_client
        from shared.db.macro_repo import get_macro_repository

        repo = get_macro_repository()
        db   = get_duckdb_client()

        def _latest(sid: str) -> float | None:
            obs = repo.read_latest_macro(sid)
            return float(obs["value"]) if obs and obs["value"] is not None else None

        y_3m   = _latest("DGS3MO"); y_2y  = _latest("DGS2")
        y_5y   = _latest("DGS5");   y_10y = _latest("DGS10")
        y_30y  = _latest("DGS30");  t10y2y = _latest("T10Y2Y")
        t10y3m = _latest("T10Y3M"); be10y  = _latest("T10YIE")
        ff     = _latest("FEDFUNDS")

        rec_prob = None
        if t10y3m is not None:
            rec_prob = float(norm.cdf(-0.6022 + -0.5517 * t10y3m))

        curve_regime = None
        if t10y2y is not None:
            if t10y2y < -0.5:  curve_regime = "inverted"
            elif t10y2y < 0:   curve_regime = "flat"
            elif t10y2y > 1.5: curve_regime = "steep"
            else:              curve_regime = "normal"

        db.execute(
            "INSERT OR REPLACE INTO yield_curve_snapshots "
            "(snapshot_date, y_3m, y_2y, y_5y, y_10y, y_30y, "
            "spread_10y_2y, spread_10y_3m, breakeven_10y, fed_funds, "
            "inversion_signal, recession_prob_12m, curve_regime) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [date.today(), y_3m, y_2y, y_5y, y_10y, y_30y,
             t10y2y, t10y3m, be10y, ff,
             t10y2y is not None and t10y2y < 0, rec_prob, curve_regime],
        )
        error_budget.record_success()
        log.info("scheduler.yield_curve.done", y_10y=y_10y, curve_regime=curve_regime,
                 rec_prob=round(rec_prob, 3) if rec_prob else None,
                 duration_ms=round((time.monotonic() - t0) * 1000))
    except Exception as exc:
        error_budget.record_error()
        log.error("scheduler.yield_curve.failed", error=str(exc)[:200])


# ─── JOB: Credit Spreads (:15 ogni 4h lun-ven) ───────────────────────────

def _job_credit_spreads() -> None:
    """HY OAS + IG OAS + TED + NFCI → stress_level."""
    t0 = time.monotonic()
    try:
        from datetime import datetime, timezone
        from shared.db.duckdb_client import get_duckdb_client
        from shared.db.macro_repo import get_macro_repository

        repo = get_macro_repository()
        db   = get_duckdb_client()

        def _latest(sid: str) -> float | None:
            obs = repo.read_latest_macro(sid)
            return float(obs["value"]) if obs and obs["value"] is not None else None

        hy_oas = _latest("BAMLH0A0HYM2"); ig_oas = _latest("BAMLC0A0CM")
        ted    = _latest("TEDRATE");      nfci   = _latest("NFCI")
        hy_ig  = (hy_oas / ig_oas) if (hy_oas and ig_oas and ig_oas > 0) else None

        if hy_oas is None: stress, score = "unknown", 0.0
        elif hy_oas < 350: stress, score = "low",      0.3
        elif hy_oas < 500: stress, score = "moderate",  0.0
        elif hy_oas < 700: stress, score = "elevated", -0.4
        else:              stress, score = "crisis",   -0.9

        db.execute(
            "INSERT OR REPLACE INTO credit_spread_signals "
            "(computed_at, hy_oas, ig_oas, hy_ig_ratio, ted_spread, "
            "nfci, stress_level, stress_score) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [datetime.now(timezone.utc), hy_oas, ig_oas, hy_ig, ted, nfci, stress, score],
        )
        error_budget.record_success()
        log.info("scheduler.credit_spreads.done", hy_oas=hy_oas, stress=stress,
                 duration_ms=round((time.monotonic() - t0) * 1000))
    except Exception as exc:
        error_budget.record_error()
        log.error("scheduler.credit_spreads.failed", error=str(exc)[:200])


# ─── JOB: VIX Strategy (:30 ogni 4h lun-ven) ─────────────────────────────
# Settimana 4: usa VixSignalCalculator + StrategyComposer (moduli definitivi)

def _job_vix_strategy() -> None:
    """VixSignalCalculator regime-aware + StrategyComposer → vix_strategy_outputs."""
    t0 = time.monotonic()
    try:
        from engine.alpha_generation.vix_signal_calculator import VixSignalCalculator
        from engine.alpha_generation.strategy_composer import StrategyComposer
        from engine.alpha_generation.macro_conviction import MacroConvictionCalculator
        from shared.db.duckdb_client import get_duckdb_client
        from shared.db.prices_repo import get_prices_repository
        from shared.db.macro_repo import get_macro_repository

        db           = get_duckdb_client()
        prices_repo  = get_prices_repository()
        macro_repo   = get_macro_repository()

        vix_calc   = VixSignalCalculator(prices_repo=prices_repo)
        macro_calc = MacroConvictionCalculator(macro_repo=macro_repo)

        composer = StrategyComposer(
            vix_calculator=vix_calc,
            macro_calculator=macro_calc,
            duckdb=db,
            profile_risk="moderate",
        )
        output = composer.run()

        # Persisti anche in vix_signals (dettaglio VIX grezzo)
        sig = output.vix_signal
        from datetime import datetime, timezone
        db.execute(
            "INSERT OR REPLACE INTO vix_signals "
            "(computed_at, vix_level, vix_zscore, vix_pct_rank, "
            "spike_detected, zscore_signal, regime, lookback_days) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [sig.computed_at, sig.vix_level, sig.vix_zscore, sig.vix_pct_rank,
             sig.spike_detected, sig.zscore_signal, sig.vix_regime, sig.lookback_bars],
        )

        error_budget.record_success()
        log.info(
            "scheduler.vix_strategy.done",
            vix=round(sig.vix_level, 2), zscore=round(sig.vix_zscore, 3),
            action=output.action, regime=output.regime_used,
            composite=round(output.composite_score, 3),
            position_size_pct=round(output.position_size_pct * 100, 1),
            duration_ms=round((time.monotonic() - t0) * 1000),
        )
    except Exception as exc:
        error_budget.record_error()
        log.error("scheduler.vix_strategy.failed", error=str(exc)[:200])


# ─── JOB: Analysis Pipeline (:45 ogni 4h lun-ven) ────────────────────────
# Settimana 8: usa CompositeSignalAggregator (modulo definitivo)

def _job_analysis_pipeline() -> None:
    """CompositeSignalAggregator → engine_composite_signal."""
    t0 = time.monotonic()
    try:
        from engine.alpha_generation.composite_signal_aggregator import (
            CompositeSignalAggregator,
        )
        from shared.db.duckdb_client import get_duckdb_client
        from shared.db.macro_repo import get_macro_repository

        db         = get_duckdb_client()
        macro_repo = get_macro_repository()

        agg    = CompositeSignalAggregator(duckdb=db, macro_repo=macro_repo)
        output = agg.compute()

        error_budget.record_success()
        log.info(
            "scheduler.pipeline.done",
            composite=round(output.composite_score, 3),
            action=output.recommended_action,
            confidence=output.confidence,
            components=output.components_used,
            duration_ms=round((time.monotonic() - t0) * 1000),
        )
    except Exception as exc:
        error_budget.record_error()
        log.error("scheduler.pipeline.failed", error=str(exc)[:200])


# ─── JOB: Manutenzione ───────────────────────────────────────────────────

def _job_backup() -> None:
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
    try:
        from scripts.duckdb_retention import main as retention_main
        retention_main()
        error_budget.record_success()
    except Exception as exc:
        error_budget.record_error()
        log.error("scheduler.retention_failed", error=str(exc))


def _check_error_budget() -> None:
    if error_budget.is_tripped:
        status = error_budget.status()
        log.warning("scheduler.error_budget_tripped",
                    error_rate_pct=status.error_rate_pct,
                    threshold_pct=status.threshold_pct)


# ═══════════════════════════════════════════════════════════════════════════
# Registro completo dei 9 job (+ 2 manutenzione)
# ═══════════════════════════════════════════════════════════════════════════

_JOB_REGISTRY: list[dict] = [
    {"id": "market_prices",    "flag": "market_data_refresh",
     "trigger": CronTrigger(day_of_week="mon-fri", hour="8,12,16,20", minute=0),
     "fn": _job_market_prices, "name": "Market prices (watched_tickers.yaml)"},

    {"id": "futures_prices",   "flag": "futures_analysis",
     "trigger": CronTrigger(day_of_week="mon-fri", hour="8,12,16,20", minute=5),
     "fn": _job_futures_prices, "name": "Futures prices + roll_yield"},

    {"id": "macro_fred",       "flag": "market_data_refresh",
     "trigger": CronTrigger(day_of_week="mon-fri", hour=7, minute=0),
     "fn": _job_macro_fred, "name": "FRED macro (28 serie)"},

    {"id": "claims_cross",     "flag": "claims_inflation_cross",
     "trigger": CronTrigger(day_of_week="thu", hour=16, minute=30),
     "fn": _job_claims_inflation, "name": "Claims/Inflation cross (giovedì)"},

    {"id": "yield_curve",      "flag": "market_data_refresh",
     "trigger": CronTrigger(day_of_week="mon-fri", hour="8,12,16,20", minute=15),
     "fn": _job_yield_curve, "name": "Yield curve + Estrella-Mishkin"},

    {"id": "credit_spreads",   "flag": "hy_credit_spread",
     "trigger": CronTrigger(day_of_week="mon-fri", hour="8,12,16,20", minute=15),
     "fn": _job_credit_spreads, "name": "Credit spreads (HY/IG OAS + TED + NFCI)"},

    {"id": "vix_strategy",     "flag": "vix_based_analysis",
     "trigger": CronTrigger(day_of_week="mon-fri", hour="8,12,16,20", minute=30),
     "fn": _job_vix_strategy, "name": "VIX strategy (Z-Score regime-aware)"},

    {"id": "analysis_pipeline","flag": "analysis_pipeline_scheduled",
     "trigger": CronTrigger(day_of_week="mon-fri", hour="8,12,16,20", minute=45),
     "fn": _job_analysis_pipeline, "name": "Analysis pipeline + Composite Signal"},

    {"id": "daily_backup",     "flag": "auto_backup_daily",
     "trigger": CronTrigger(hour=2, minute=0),
     "fn": _job_backup, "name": "Daily backup"},

    {"id": "monthly_retention","flag": "auto_retention_cleanup",
     "trigger": CronTrigger(day=1, hour=3, minute=0),
     "fn": _job_retention, "name": "Monthly retention cleanup"},
]


def main(dry_run: bool = False) -> int:
    configure_logging()
    scheduler = BlockingScheduler(timezone="UTC")
    registered = 0

    for job in _JOB_REGISTRY:
        flag = job.get("flag")
        if flag and not is_enabled(flag):
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
        scheduler.add_job(_check_error_budget,
                          trigger=CronTrigger(minute="*"),
                          id="error_budget_monitor", replace_existing=True)

    log.info("scheduler.v2.ready", registered=registered, dry_run=dry_run)
    if dry_run:
        return 0

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("scheduler.stopped")
    return 0


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="MarketAI Scheduler v2.0")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    sys.exit(main(dry_run=args.dry_run))
