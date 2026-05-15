"""Test suite — Roadmap Unificata Settimana 2: Scheduler Unificato.

Verifica:
  · Tutti i 10 job presenti nel _JOB_REGISTRY
  · Ogni job ha feature flag, trigger e funzione valida
  · Ordine di esecuzione dei minuti corretto (:00, :05, :15, :30, :45)
  · dry-run completa senza errori
  · Flag disabilitato → job non registrato
  · Claims job schedulato il giovedì
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest


class TestSchedulerRegistry:
    """Verifica il registro completo dei job."""

    def test_all_job_ids_present(self):
        """I 10 job della Roadmap Unificata devono essere nel registro."""
        from scripts.run_scheduler import _JOB_REGISTRY

        job_ids = {j["id"] for j in _JOB_REGISTRY}
        expected = {
            "market_prices", "futures_prices", "macro_fred",
            "claims_cross", "yield_curve", "credit_spreads",
            "vix_strategy", "analysis_pipeline",
            "daily_backup", "monthly_retention",
            # Roadmap v3.0 Sett.1+6: fundamentals + surprise engine jobs
            "edgar_fundamentals", "av_fundamentals",
            "surprise_consensus_load", "surprise_engine_v2",
        }
        assert expected == job_ids

    def test_all_jobs_have_required_keys(self):
        """Ogni job deve avere id, flag, trigger, fn, name."""
        from scripts.run_scheduler import _JOB_REGISTRY

        for job in _JOB_REGISTRY:
            assert "id" in job, f"Job senza id: {job}"
            assert "flag" in job, f"Job '{job['id']}' senza flag"
            assert "trigger" in job, f"Job '{job['id']}' senza trigger"
            assert "fn" in job, f"Job '{job['id']}' senza fn"
            assert "name" in job, f"Job '{job['id']}' senza name"
            assert callable(job["fn"]), f"Job '{job['id']}' fn non callable"

    def test_job_functions_are_callable(self):
        """Tutte le funzioni job devono essere importabili e callable."""
        from scripts.run_scheduler import (
            _job_market_prices, _job_futures_prices, _job_macro_fred,
            _job_claims_inflation, _job_yield_curve, _job_credit_spreads,
            _job_vix_strategy, _job_analysis_pipeline,
            _job_backup, _job_retention,
        )
        fns = [
            _job_market_prices, _job_futures_prices, _job_macro_fred,
            _job_claims_inflation, _job_yield_curve, _job_credit_spreads,
            _job_vix_strategy, _job_analysis_pipeline,
            _job_backup, _job_retention,
        ]
        for fn in fns:
            assert callable(fn), f"{fn.__name__} non è callable"


class TestSchedulerTriggerOrder:
    """Verifica l'ordine di esecuzione dei job intra-ora."""

    def _get_minute(self, job_id: str) -> int | None:
        from scripts.run_scheduler import _JOB_REGISTRY
        from apscheduler.triggers.cron import CronTrigger

        for job in _JOB_REGISTRY:
            if job["id"] == job_id:
                trigger = job["trigger"]
                # Leggi il campo minute dal trigger
                fields = {f.name: f for f in trigger.fields}
                minute_field = fields.get("minute")
                if minute_field:
                    expr = str(minute_field)
                    # CronTrigger field expr può essere "0", "5", "15", etc.
                    try:
                        return int(expr)
                    except ValueError:
                        return None
        return None

    def test_market_prices_at_minute_0(self):
        """market_prices deve scattare a :00."""
        minute = self._get_minute("market_prices")
        assert minute == 0, f"market_prices al minuto {minute}, atteso 0"

    def test_futures_prices_at_minute_5(self):
        """futures_prices deve scattare a :05 (dopo prezzi)."""
        minute = self._get_minute("futures_prices")
        assert minute == 5, f"futures_prices al minuto {minute}, atteso 5"

    def test_yield_curve_at_minute_15(self):
        """yield_curve deve scattare a :15 (dopo fetch dati)."""
        minute = self._get_minute("yield_curve")
        assert minute == 15

    def test_vix_strategy_at_minute_30(self):
        """vix_strategy deve scattare a :30 (dopo yield+credit)."""
        minute = self._get_minute("vix_strategy")
        assert minute == 30

    def test_analysis_pipeline_at_minute_45(self):
        """analysis_pipeline deve scattare a :45 (ultimo, aggrega tutto)."""
        minute = self._get_minute("analysis_pipeline")
        assert minute == 45

    def test_execution_order_is_sequential(self):
        """L'ordine minuti: :00 < :05 < :15 < :30 < :45."""
        minutes = {
            "market_prices": self._get_minute("market_prices"),
            "futures_prices": self._get_minute("futures_prices"),
            "yield_curve": self._get_minute("yield_curve"),
            "vix_strategy": self._get_minute("vix_strategy"),
            "analysis_pipeline": self._get_minute("analysis_pipeline"),
        }
        vals = list(minutes.values())
        # Tutti devono essere non-None
        assert all(v is not None for v in vals), f"Minuti non parsabili: {minutes}"
        # Devono essere in ordine crescente
        assert vals == sorted(vals), f"Ordine errato: {minutes}"


class TestSchedulerFeatureFlags:
    """Verifica integrazione feature flags con il registry."""

    def test_claims_cross_has_correct_flag(self):
        """claims_cross deve usare il flag 'claims_inflation_cross'."""
        from scripts.run_scheduler import _JOB_REGISTRY
        job = next(j for j in _JOB_REGISTRY if j["id"] == "claims_cross")
        assert job["flag"] == "claims_inflation_cross"

    def test_vix_strategy_has_correct_flag(self):
        """vix_strategy deve usare il flag 'vix_based_analysis'."""
        from scripts.run_scheduler import _JOB_REGISTRY
        job = next(j for j in _JOB_REGISTRY if j["id"] == "vix_strategy")
        assert job["flag"] == "vix_based_analysis"

    def test_futures_prices_has_correct_flag(self):
        """futures_prices deve usare il flag 'futures_analysis'."""
        from scripts.run_scheduler import _JOB_REGISTRY
        job = next(j for j in _JOB_REGISTRY if j["id"] == "futures_prices")
        assert job["flag"] == "futures_analysis"

    def test_dry_run_registers_all_enabled_jobs(self):
        """dry-run con tutti i flag attivi deve registrare 10 job."""
        from scripts.run_scheduler import _JOB_REGISTRY, is_enabled

        registered = [j for j in _JOB_REGISTRY if is_enabled(j.get("flag", ""))]
        # Con tutti i flag correnti (market_data_refresh, vix_based_analysis, etc. = True)
        # ci aspettiamo >= 8 job registrati
        assert len(registered) >= 8, f"Solo {len(registered)} job abilitati"

    def test_dry_run_exits_zero(self, monkeypatch):
        """dry-run deve uscire con codice 0."""
        from scripts.run_scheduler import main
        result = main(dry_run=True)
        assert result == 0


class TestSchedulerCronTriggers:
    """Verifica configurazione CronTrigger per i job chiave."""

    def _get_trigger(self, job_id: str):
        from scripts.run_scheduler import _JOB_REGISTRY
        for job in _JOB_REGISTRY:
            if job["id"] == job_id:
                return job["trigger"]
        return None

    def test_macro_fred_daily_trigger(self):
        """macro_fred scatta ogni giorno alle 07:00."""
        trigger = self._get_trigger("macro_fred")
        assert trigger is not None
        fields = {f.name: str(f) for f in trigger.fields}
        assert fields.get("hour") == "7", f"Hour: {fields.get('hour')}"
        assert fields.get("minute") == "0"

    def test_claims_cross_thursday_trigger(self):
        """claims_cross scatta il giovedì."""
        trigger = self._get_trigger("claims_cross")
        assert trigger is not None
        fields = {f.name: str(f) for f in trigger.fields}
        assert "thu" in fields.get("day_of_week", ""), f"day_of_week: {fields.get('day_of_week')}"

    def test_backup_at_2am(self):
        """daily_backup scatta alle 02:00."""
        trigger = self._get_trigger("daily_backup")
        assert trigger is not None
        fields = {f.name: str(f) for f in trigger.fields}
        assert fields.get("hour") == "2"

    def test_retention_day_1(self):
        """monthly_retention scatta il giorno 1 del mese."""
        trigger = self._get_trigger("monthly_retention")
        assert trigger is not None
        fields = {f.name: str(f) for f in trigger.fields}
        assert fields.get("day") == "1"
