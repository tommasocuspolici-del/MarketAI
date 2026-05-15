"""Job fetch-dati per lo scheduler MarketAI.

Contiene i job di acquisizione dati:
  · _job_market_prices   — OHLCV ticker (ogni 4h, lun-ven :00)
  · _job_futures_prices  — Futures + roll/basis/OI (ogni 4h :05)
  · _job_macro_fred      — 28 serie FRED (07:00 lun-ven)
  · _job_claims_inflation— Claims/Inflation cross (giovedì 16:30)
  · _job_yield_curve     — Yield curve snapshot (ogni 4h :15)
  · _job_credit_spreads  — HY/IG OAS + TED + NFCI (ogni 4h :15)

Regola 2 (SRP): solo fetch/persist dati — nessun calcolo analitico.
Importato da run_scheduler.py via _JOB_REGISTRY.

ANTI-REGRESSIONE: importare scheduler_utils PRIMA di qualsiasi
modulo app per garantire che sys.path sia configurato correttamente.
"""
from __future__ import annotations
import time
from scripts.scheduler_utils import _PROJECT_ROOT, _run_async, error_budget, log

__version__ = "2.2.0"
__all__ = [
    "_job_market_prices", "_job_futures_prices",
    "_job_macro_fred", "_job_claims_inflation",
    "_job_yield_curve", "_job_credit_spreads",
    "_job_labour_jolts", "_job_labour_claims_cycle", "_job_labour_payroll",
]

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


# ─── JOB: Labour Market JOLTS (3° mercoledì mese, 17:00 UTC) ────────────────
# REGOLA 29: Gated da labour_market_fetcher.
# JOLTSAnalyzer fetcha da FRED e persiste in jolts_monthly.
# Richiede FRED_API_KEY in .env.

def _job_labour_jolts() -> None:
    """Fetcha dati JOLTS da FRED e persiste in jolts_monthly."""
    t0 = time.monotonic()
    try:
        from shared.db.duckdb_client import get_duckdb_client
        from engine.analytics.labour_market.jolts_analyzer import JOLTSAnalyzer
        from shared.feature_flags import is_enabled

        if not is_enabled("labour_market_fetcher"):
            log.debug("scheduler.labour_jolts.flag_disabled")
            return

        db     = get_duckdb_client()
        jolts  = JOLTSAnalyzer(duckdb=db)
        signal = jolts.analyze()
        error_budget.record_success()
        log.info(
            "scheduler.labour_jolts.done",
            regime=signal.regime,
            score=round(signal.labour_score, 3),
            beveridge_gap=round(signal.beveridge_gap, 2),
            duration_ms=round((time.monotonic() - t0) * 1000),
        )
    except Exception as exc:
        error_budget.record_error()
        log.error("scheduler.labour_jolts.failed", error=str(exc)[:200])


# ─── JOB: Labour Market Claims Cycle (ogni giovedì, 08:30 UTC) ──────────────
# REGOLA 29: Gated da labour_market_fetcher.
# ClaimsCycleDetector fetcha ICSA da FRED e persiste in claims_cycle.

def _job_labour_claims_cycle() -> None:
    """Fetcha Initial Claims da FRED, rileva il regime e persiste in claims_cycle."""
    t0 = time.monotonic()
    try:
        from shared.db.duckdb_client import get_duckdb_client
        from engine.analytics.labour_market.claims_cycle_detector import ClaimsCycleDetector
        from shared.feature_flags import is_enabled

        if not is_enabled("labour_market_fetcher"):
            log.debug("scheduler.labour_claims.flag_disabled")
            return

        db     = get_duckdb_client()
        det    = ClaimsCycleDetector(duckdb=db)
        signal = det.detect()
        error_budget.record_success()
        log.info(
            "scheduler.labour_claims.done",
            regime=signal.cycle_regime,
            claims=signal.initial_claims,
            ma_4wk=round(signal.claims_4wk_ma, 0),
            strength=round(signal.signal_strength, 3),
            duration_ms=round((time.monotonic() - t0) * 1000),
        )
    except Exception as exc:
        error_budget.record_error()
        log.error("scheduler.labour_claims.failed", error=str(exc)[:200])


# ─── JOB: Labour Market Payroll (1° venerdì mese, 08:30 UTC) ────────────────
# REGOLA 29: Gated da labour_market_fetcher.
# PayrollDecomposer fetcha NFP settoriale da FRED e persiste in payroll_sector.

def _job_labour_payroll() -> None:
    """Fetcha NFP settoriale da FRED, decompone e persiste in payroll_sector."""
    t0 = time.monotonic()
    try:
        from shared.db.duckdb_client import get_duckdb_client
        from engine.analytics.labour_market.payroll_decomposer import PayrollDecomposer
        from shared.feature_flags import is_enabled

        if not is_enabled("labour_market_fetcher"):
            log.debug("scheduler.labour_payroll.flag_disabled")
            return

        db     = get_duckdb_client()
        decomp = PayrollDecomposer(duckdb=db)
        signal = decomp.decompose()
        error_budget.record_success()
        log.info(
            "scheduler.labour_payroll.done",
            nfp_k=round(signal.nfp_total, 1),
            cyclical_ratio=round(signal.cyclical_ratio, 3),
            score=round(signal.payroll_score, 3),
            duration_ms=round((time.monotonic() - t0) * 1000),
        )
    except Exception as exc:
        error_budget.record_error()
        log.error("scheduler.labour_payroll.failed", error=str(exc)[:200])

