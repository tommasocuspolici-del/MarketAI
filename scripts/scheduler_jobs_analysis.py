"""Job analisi per lo scheduler MarketAI.

Contiene i job di analisi e segnale:
  · _job_vix_strategy          — VIX regime-aware (ogni 4h :30)
  · _job_analysis_pipeline     — Composite Signal aggregato (ogni 4h :45)
  · _job_edgar_fundamentals    — EDGAR XBRL income+balance (domenica 06:00)
  · _job_av_fundamentals       — AV P/E EV/EBITDA (lunedì 07:30)
  · _job_surprise_consensus_loader — Consensus YAML+FRED (lunedì 06:45)
  · _job_surprise_engine_v2    — Surprise pipeline completa (lunedì 08:00)
  · _job_backup                — Backup DuckDB (02:00 daily)
  · _job_retention             — Pulizia retention (01 di ogni mese 03:00)

Regola 2 (SRP): solo analisi/segnali/manutenzione — nessun fetch raw dati.
Importato da run_scheduler.py via _JOB_REGISTRY.

ANTI-REGRESSIONE: importare scheduler_utils PRIMA di qualsiasi
modulo app per garantire che sys.path sia configurato correttamente.
"""
from __future__ import annotations
import time
from scripts.scheduler_utils import _PROJECT_ROOT, _run_async, error_budget, log

__version__ = "2.2.0"
__all__ = [
    "_job_vix_strategy", "_job_analysis_pipeline",
    "_job_edgar_fundamentals", "_job_av_fundamentals",
    "_job_surprise_consensus_loader", "_job_surprise_engine_v2",
    "_job_labour_regime", "_job_labour_forecast",
    "_job_backup", "_job_retention",
]

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


# ─── JOB: EDGAR Fundamentals (domenica 06:00 UTC) ────────────────────────────
# REGOLA 29: Gated da edgar_fundamentals_scheduler + edgar_bulk_download.
# REGOLA 28: RateLimitManager impone ≤ 10 req/min a SEC EDGAR.
# Il job usa i ticker della sezione 'equities' in watched_tickers.yaml.
# Ticker senza CIK mappato vengono skippati con warning (non bloccano il batch).
#
# ANTI-REGRESSIONE: import DENTRO la funzione per evitare che l'import
# di aiohttp/SECEdgarFetcher al module-level rallenti l'avvio scheduler.

def _job_edgar_fundamentals() -> None:
    """Scarica bilanci EDGAR XBRL e aggiorna fundamentals_edgar."""
    t0 = time.monotonic()
    try:
        import yaml
        from engine.market_data.fetchers.edgar_fetcher import SECEdgarFetcher
        from engine.market_data.fetchers.edgar_fundamentals_parser import FundamentalsAggregator
        from shared.db.fundamentals_repo import get_fundamentals_repository

        # Carica mapping ticker → CIK dal YAML (sezione edgar_cik)
        # Se la sezione non esiste, non ci sono ticker configurati → skip
        cfg_path = _PROJECT_ROOT / "config" / "watched_tickers.yaml"
        with cfg_path.open() as f:
            cfg = yaml.safe_load(f)
        ticker_to_cik: dict[str, str] = cfg.get("edgar_cik", {})

        if not ticker_to_cik:
            log.info("scheduler.edgar_fundamentals.no_cik_map")
            return

        fetcher = SECEdgarFetcher()
        aggregator = FundamentalsAggregator()
        repo = get_fundamentals_repository()

        total_rows = 0
        for ticker, cik in ticker_to_cik.items():
            try:
                facts = _run_async(
                    fetcher.fetch_company_facts(
                        ticker=ticker,
                        cik=str(cik),
                        # Filtra solo i concept che ci servono per ridurre RAM
                        metrics_filter=[
                            "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                            "GrossProfit", "OperatingIncomeLoss", "NetIncomeLoss",
                            "EarningsPerShareDiluted",
                            "Assets", "LongTermDebt", "ShortTermBorrowings",
                            "StockholdersEquity",
                            "NetCashProvidedByUsedInOperatingActivities",
                            "PaymentsToAcquirePropertyPlantAndEquipment",
                        ],
                    )
                )
                df = aggregator.aggregate(facts)
                rows = repo.write_edgar(df)
                total_rows += rows
                log.info(
                    "scheduler.edgar_fundamentals.ticker_done",
                    ticker=ticker,
                    rows=rows,
                )
            except Exception as exc:
                # Skip ticker singolo — non blocca il batch (partial success)
                log.warning(
                    "scheduler.edgar_fundamentals.ticker_skip",
                    ticker=ticker,
                    error=str(exc)[:200],
                )
                continue

        duration_ms = int((time.monotonic() - t0) * 1000)
        error_budget.record_success()
        log.info(
            "scheduler.edgar_fundamentals.done",
            total_rows=total_rows,
            duration_ms=duration_ms,
        )

    except Exception as exc:
        error_budget.record_error()
        log.error("scheduler.edgar_fundamentals.failed", error=str(exc)[:200])


# ─── JOB: Alpha Vantage Fundamentals (lunedì 07:30 UTC) ──────────────────────
# REGOLA 29: Gated da av_fundamentals_scheduler + alpha_vantage_premium.
# REGOLA 28: RateLimitManager impone ≤ 5 req/min ad Alpha Vantage.
# Il job aggiorna solo i valuation ratios (P/E, EV/EBITDA, ecc.).
# Non sovrascrive i dati EDGAR — tabelle separate.
#
# ANTI-REGRESSIONE: il flag alpha_vantage_premium DEVE essere true E
# ALPHA_VANTAGE_KEY deve essere configurata in .env — se manca una delle due
# condizioni il costruttore lancia FeatureDisabledError/ConfigurationError,
# che viene catturata qui e registrata come error_budget hit.

def _job_av_fundamentals() -> None:
    """Aggiorna fundamentals_valuation con P/E, EV/EBITDA da Alpha Vantage."""
    t0 = time.monotonic()
    try:
        import yaml
        from engine.market_data.fetchers.alpha_vantage_fundamentals_fetcher import (
            AlphaVantageFundamentalsFetcher,
        )
        from shared.db.fundamentals_repo import get_fundamentals_repository
        from shared.exceptions import FeatureDisabledError, ConfigurationError

        # Carica la lista dei ticker azionari da watched_tickers.yaml
        cfg_path = _PROJECT_ROOT / "config" / "watched_tickers.yaml"
        with cfg_path.open() as f:
            cfg = yaml.safe_load(f)
        equities: list[str] = cfg.get("equities", [])

        if not equities:
            log.info("scheduler.av_fundamentals.no_tickers")
            return

        try:
            fetcher = AlphaVantageFundamentalsFetcher()
        except (FeatureDisabledError, ConfigurationError) as exc:
            # Flag disabilitato o chiave mancante → skip senza error_budget hit
            log.warning("scheduler.av_fundamentals.not_configured", reason=str(exc)[:100])
            return

        repo = get_fundamentals_repository()
        total_rows = 0

        for ticker in equities:
            try:
                df = _run_async(fetcher.fetch_valuation(ticker))
                rows = repo.write_valuation(df)
                total_rows += rows
                log.info(
                    "scheduler.av_fundamentals.ticker_done",
                    ticker=ticker,
                    rows=rows,
                )
            except Exception as exc:
                # Skip ticker singolo — rate limit AV non blocca il batch
                log.warning(
                    "scheduler.av_fundamentals.ticker_skip",
                    ticker=ticker,
                    error=str(exc)[:200],
                )
                continue

        duration_ms = int((time.monotonic() - t0) * 1000)
        error_budget.record_success()
        log.info(
            "scheduler.av_fundamentals.done",
            total_rows=total_rows,
            duration_ms=duration_ms,
        )

    except Exception as exc:
        error_budget.record_error()
        log.error("scheduler.av_fundamentals.failed", error=str(exc)[:200])


# ─── JOB: Surprise Consensus Loader (lunedì 06:45 UTC) ───────────────────────
# REGOLA 29: Gated da surprise_consensus_loader.
# Carica stime consensus da YAML manuale e FRED-derived.
# Deve girare PRIMA del job surprise_engine_v2 (08:00).
# ANTI-REGRESSIONE: import dentro la funzione per evitare import circular
# tra SurpriseAggregatorV2 e ConsensusLoader.

def _job_surprise_consensus_loader() -> None:
    """Carica consensus estimates YAML + FRED-derived in consensus_estimates."""
    t0 = time.monotonic()
    try:
        from engine.analytics.surprise_engine.consensus_loader import ConsensusLoader
        loader = ConsensusLoader()
        yaml_b = loader.load_yaml()
        fred_b = loader.load_fred_derived()
        n_yaml = loader.save(yaml_b)
        n_fred = loader.save(fred_b)
        duration_ms = int((time.monotonic() - t0) * 1000)
        error_budget.record_success()
        log.info(
            "scheduler.surprise_consensus.done",
            yaml_rows=n_yaml, fred_rows=n_fred, duration_ms=duration_ms,
        )
    except Exception as exc:
        error_budget.record_error()
        log.error("scheduler.surprise_consensus.failed", error=str(exc)[:200])


# ─── JOB: Surprise Engine v2 Full Pipeline (lunedì 08:00 UTC) ────────────────
# REGOLA 29: Gated da surprise_scheduler.
# Dipende dal consensus_loader job (06:45) e da macro_fred (07:00).
# Output: aggiorna economic_consensus + sector_surprise_index + surprise_signal.

def _job_surprise_engine_v2() -> None:
    """Esegue la pipeline completa Surprise Engine v2."""
    t0 = time.monotonic()
    try:
        from engine.analytics.surprise_engine.surprise_aggregator_v2 import SurpriseAggregatorV2
        aggregator = SurpriseAggregatorV2()
        result     = aggregator.run_full_pipeline()
        duration_ms = int((time.monotonic() - t0) * 1000)
        error_budget.record_success()
        log.info(
            "scheduler.surprise_v2.done",
            rows=result.rows_computed,
            sectors=len(result.sector_indices),
            signal=round(result.signal.signal_value, 3) if result.signal else None,
            acc_before=result.accuracy_before,
            acc_after=result.accuracy_after,
            calibrated=result.calibrated,
            duration_ms=duration_ms,
        )
    except Exception as exc:
        error_budget.record_error()
        log.error("scheduler.surprise_v2.failed", error=str(exc)[:200])


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


# ─── JOB: Labour Regime Classifier (venerdì 18:00 UTC) ──────────────────────
# REGOLA 29: Gated da labour_market_scheduler.
# Legge da jolts_monthly + claims_cycle in DuckDB, classifica il regime
# aggregato e persiste in labour_regime.
# Deve girare DOPO _job_labour_jolts e _job_labour_claims_cycle.

def _job_labour_regime() -> None:
    """Classifica il regime aggregato del mercato del lavoro da DB e persiste."""
    import time
    t0 = time.monotonic()
    try:
        from shared.db.duckdb_client import get_duckdb_client
        from shared.feature_flags import is_enabled
        from engine.analytics.labour_market.jolts_analyzer import JOLTSAnalyzer
        from engine.analytics.labour_market.claims_cycle_detector import ClaimsCycleDetector
        from engine.analytics.labour_market.payroll_decomposer import PayrollDecomposer
        from engine.analytics.labour_market.labour_regime_classifier import LabourRegimeClassifier

        if not is_enabled("labour_market_scheduler"):
            log.debug("scheduler.labour_regime.flag_disabled")
            return

        db = get_duckdb_client()

        # Leggi segnali più recenti da DuckDB (no fetch API)
        jolts_signal  = JOLTSAnalyzer(duckdb=db).analyze()
        claims_signal = ClaimsCycleDetector(duckdb=db).detect()

        # Payroll score da PayrollDecomposer (0 se dati mancanti)
        try:
            payroll_score = PayrollDecomposer(duckdb=db).decompose().payroll_score
        except Exception:
            payroll_score = 0.0

        classifier = LabourRegimeClassifier(duckdb=db)
        result = classifier.classify(jolts_signal, claims_signal, payroll_score)

        error_budget.record_success()
        log.info(
            "scheduler.labour_regime.done",
            regime=result.regime,
            score=round(result.composite_score, 3),
            confidence=round(result.confidence, 3),
            duration_ms=round((time.monotonic() - t0) * 1000),
        )
    except Exception as exc:
        error_budget.record_error()
        log.error("scheduler.labour_regime.failed", error=str(exc)[:200])


# ─── JOB: Labour Forecast (lunedì 10:00 UTC) ────────────────────────────────
# REGOLA 29: Gated da labour_market_forecasting.
# Legge serie storiche da DuckDB, fitta ARIMA+Ridge, genera forecast
# 1M/3M/6M e persiste in labour_forecasts.

def _job_labour_forecast() -> None:
    """Genera forecast 1M/3M/6M per UNRATE e Claims e persiste in labour_forecasts."""
    import time
    from datetime import datetime, UTC
    t0 = time.monotonic()
    try:
        from shared.db.duckdb_client import get_duckdb_client
        from shared.feature_flags import is_enabled
        from engine.analytics.labour_market.labour_forecast_engine import LabourForecastEngine

        import numpy as np
        import pandas as pd

        if not is_enabled("labour_market_forecasting"):
            log.debug("scheduler.labour_forecast.flag_disabled")
            return

        db = get_duckdb_client()

        # ── Carica serie storiche da DuckDB ──────────────────────────────────
        def _load_series(query: str, col: str) -> pd.Series:
            rows = db.query(query)
            if not rows:
                return pd.Series([], dtype=float)
            df = pd.DataFrame(rows, columns=["date", col])
            df["date"] = pd.to_datetime(df["date"])
            return df.set_index("date")[col].dropna().sort_index()

        unrate_series = _load_series(
            "SELECT ts, value FROM macro_series "
            "WHERE series_id='UNRATE' ORDER BY ts ASC",
            "unrate",
        )
        claims_ma_series = _load_series(
            "SELECT week_ending, claims_4wk_ma FROM claims_cycle "
            "WHERE claims_4wk_ma IS NOT NULL ORDER BY week_ending ASC",
            "claims_4wk_ma",
        )
        quits_series = _load_series(
            "SELECT series_date, quits_rate FROM jolts_monthly "
            "WHERE quits_rate IS NOT NULL ORDER BY series_date ASC",
            "quits_rate",
        )

        total_persisted = 0

        for target_name, target_series in [
            ("unemployment_rate", unrate_series),
            ("claims_4wk_ma",     claims_ma_series),
            ("quits_rate",        quits_series),
        ]:
            if len(target_series) < 24:   # min 24 obs per fit stabile
                log.debug("scheduler.labour_forecast.skip_insufficient",
                          metric=target_name, n=len(target_series))
                continue

            # Features: lag 1-3 della stessa serie (auto-regressive)
            n = len(target_series)
            feat_df = pd.DataFrame({
                "lag1": target_series.shift(1),
                "lag2": target_series.shift(2),
                "lag3": target_series.shift(3),
            }).dropna()
            aligned = target_series.iloc[-len(feat_df):]

            try:
                engine = LabourForecastEngine()
                engine.fit(target=aligned, features=feat_df)

                # Future features: ultima riga features (shift forward)
                last_feat = feat_df.iloc[[-1]].copy()
                last_feat.columns = feat_df.columns
                result = engine.forecast(
                    horizons=["1M", "3M", "6M"],
                    future_features=last_feat,
                    target_metric=target_name,
                )

                # Persist ogni bundle in labour_forecasts
                for bundle in result.bundles:
                    db.execute(
                        """
                        INSERT INTO labour_forecasts
                            (generated_at, horizon, target_metric,
                             forecast_value, forecast_lower, forecast_upper,
                             model_used, arima_forecast, ridge_forecast)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (generated_at, horizon, target_metric)
                        DO UPDATE SET
                            forecast_value = excluded.forecast_value,
                            model_used     = excluded.model_used
                        """,
                        [
                            datetime.now(UTC).isoformat(),
                            bundle.horizon, bundle.target_metric,
                            bundle.point_forecast, bundle.lower_10,
                            bundle.upper_90, bundle.model_used,
                            bundle.arima_forecast, bundle.ridge_forecast,
                        ],
                    )
                    total_persisted += 1

            except Exception as exc:
                log.warning("scheduler.labour_forecast.metric_failed",
                            metric=target_name, error=str(exc)[:120])
                continue

        error_budget.record_success()
        log.info(
            "scheduler.labour_forecast.done",
            bundles_persisted=total_persisted,
            duration_ms=round((time.monotonic() - t0) * 1000),
        )
    except Exception as exc:
        error_budget.record_error()
        log.error("scheduler.labour_forecast.failed", error=str(exc)[:200])


# ═══════════════════════════════════════════════════════════════════════════
# Registro completo dei 9 job (+ 2 manutenzione)
# ═══════════════════════════════════════════════════════════════════════════
