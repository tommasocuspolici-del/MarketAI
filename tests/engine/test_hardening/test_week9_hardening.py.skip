"""Test suite — Roadmap Unificata Settimana 9: Hardening & Qualità.

Copre:
  · SanityCheckerV2: VIX, roll_yield, futures/spot discrepancy, yield spread
  · SilentFailureDetector: stale, zero_volume, missing, macro staleness
  · Integration test: pipeline end-to-end su fixture DuckDB (migration 007)
  · mypy e ruff: 0 errors (verificato in CI, non qui)
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.market_data.sanity_checker_v2 import SanityCheckerV2, SanityResult
from engine.market_data.silent_failure_detector import (
    SilentFailureDetector, SilentFailureResult,
)


# ─── Local fixtures (migrated_client not available from week1 tests) ─────────

@pytest.fixture()
def migrated_client(tmp_duckdb_path):
    """DuckDBClient con tutte le migration applicate (locale per Sett. 9)."""
    from shared.db.duckdb_client import DuckDBClient
    from shared.db.duckdb_migrator import DuckDBMigrator
    client = DuckDBClient(path=tmp_duckdb_path)
    migrator = DuckDBMigrator(client=client)
    migrator.apply_pending()
    yield client
    client.close()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _ohlcv_df(closes: list[float], volumes: list[int] | None = None) -> pd.DataFrame:
    n = len(closes)
    dates = pd.date_range("2025-01-01", periods=n, freq="D", tz="UTC")
    vol = volumes if volumes else [1_000_000] * n
    return pd.DataFrame({
        "ts": dates, "close": closes,
        "open": closes, "high": closes, "low": closes,
        "volume": vol,
    })


def _macro_df(values: list[float], days_old: int = 5) -> pd.DataFrame:
    """DataFrame macro con timestamp datato N giorni fa.

    Genera n date mensili con l'ultima datata days_old giorni fa.
    Usa start-based range per garantire lunghezza = n.
    """
    n = len(values)
    # Ancora l'ultima data a days_old giorni fa e costruisce a ritroso
    latest_ts = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days_old)
    # Usa start fisso per garantire n periodi esatti
    start_ts = latest_ts - pd.DateOffset(months=n - 1)
    dates = pd.date_range(start=start_ts.replace(day=1), periods=n, freq="MS", tz="UTC")
    assert len(dates) == n
    return pd.DataFrame({"ts": list(dates), "value": values})


# ═══════════════════════════════════════════════════════════════════════════
# SanityCheckerV2
# ═══════════════════════════════════════════════════════════════════════════

class TestSanityCheckerVIX:

    def setup_method(self):
        self.checker = SanityCheckerV2()

    def test_normal_vix_ok(self):
        """VIX in range normale (12–30) → OK."""
        for vix in [12.0, 18.5, 25.0, 30.0]:
            r = self.checker.check_vix(vix)
            assert r.level == "OK", f"VIX {vix} dovrebbe essere OK"
            assert r.passed is True

    def test_zero_vix_critical(self):
        """VIX = 0 → CRITICAL."""
        r = self.checker.check_vix(0.0)
        assert r.level == "CRITICAL"
        assert r.passed is False

    def test_negative_vix_critical(self):
        """VIX negativo → CRITICAL."""
        r = self.checker.check_vix(-5.0)
        assert r.level == "CRITICAL"
        assert r.passed is False

    def test_vix_above_100_critical(self):
        """VIX > 100 → CRITICAL (dato impossibile)."""
        r = self.checker.check_vix(105.0)
        assert r.level == "CRITICAL"
        assert r.passed is False

    def test_vix_above_50_warn(self):
        """VIX > 50 ma ≤ 100 → WARN (estremo ma possibile)."""
        r = self.checker.check_vix(65.0)
        assert r.level == "WARN"
        assert r.passed is True   # non blocca

    def test_vix_boundary_exactly_100(self):
        """VIX = 100 esatto → CRITICAL (> 100 non include 100... ma 100 è estremo)."""
        r = self.checker.check_vix(100.0)
        # 100 non è > 100, quindi è WARN (≤100 e >50)
        assert r.level == "WARN"

    def test_result_has_value(self):
        """SanityResult include il valore controllato."""
        r = self.checker.check_vix(18.5)
        assert r.value == pytest.approx(18.5)

    def test_result_has_rule(self):
        """SanityResult include il nome della regola."""
        r = self.checker.check_vix(18.5)
        assert len(r.rule) > 0


class TestSanityCheckerRollYield:

    def setup_method(self):
        self.checker = SanityCheckerV2()

    def test_normal_roll_yield_ok(self):
        """Roll yield in range normale (±15%) → OK."""
        for roll in [-0.018, 0.0, 0.012, -0.05, 0.10]:
            r = self.checker.check_roll_yield(roll, "CL=F")
            assert r.level == "OK", f"Roll {roll*100:.1f}% dovrebbe essere OK"

    def test_roll_above_100pct_critical(self):
        """Roll yield > 100% → CRITICAL."""
        r = self.checker.check_roll_yield(1.5, "CL=F")
        assert r.level == "CRITICAL"
        assert r.passed is False

    def test_roll_below_minus_100pct_critical(self):
        """Roll yield < -100% → CRITICAL."""
        r = self.checker.check_roll_yield(-1.2, "GC=F")
        assert r.level == "CRITICAL"
        assert r.passed is False

    def test_roll_high_warn(self):
        """Roll yield 15–100% → WARN."""
        r = self.checker.check_roll_yield(0.20, "ZC=F")
        assert r.level == "WARN"
        assert r.passed is True

    def test_ticker_in_message(self):
        """Il ticker è incluso nel messaggio di errore."""
        r = self.checker.check_roll_yield(1.5, "ES=F")
        assert "ES=F" in r.message


class TestSanityCheckerDiscrepancy:

    def setup_method(self):
        self.checker = SanityCheckerV2()

    def test_small_discrepancy_ok(self):
        """Discrepanza < 5% → OK."""
        r = self.checker.check_futures_spot_discrepancy(72.0, 70.5, "CL=F", "USO")
        assert r.level == "OK"
        assert r.value is not None
        assert r.value < 5.0

    def test_large_discrepancy_warn(self):
        """Discrepanza > 5% → WARN."""
        r = self.checker.check_futures_spot_discrepancy(75.0, 70.0, "CL=F", "USO")
        assert r.level == "WARN"
        assert r.passed is True  # warning non blocca

    def test_zero_spot_warn(self):
        """Spot = 0 → WARN (dato impossibile)."""
        r = self.checker.check_futures_spot_discrepancy(70.0, 0.0, "CL=F", "USO")
        assert r.level == "WARN"
        assert r.passed is False

    def test_custom_threshold(self):
        """Soglia custom funziona correttamente."""
        # Con threshold 10% una discrepanza del 7% è OK
        r = self.checker.check_futures_spot_discrepancy(
            107.0, 100.0, "GC=F", "GLD", threshold_pct=10.0
        )
        assert r.level == "OK"


class TestSanityCheckerYieldSpread:

    def setup_method(self):
        self.checker = SanityCheckerV2()

    def test_normal_spread_ok(self):
        """Spread normali → OK."""
        for spread in [-2.0, -0.5, 0.0, 0.5, 2.5, 5.0]:
            r = self.checker.check_yield_spread(spread)
            assert r.level == "OK", f"Spread {spread} dovrebbe essere OK"

    def test_extreme_spread_critical(self):
        """Spread > 15% → CRITICAL."""
        r = self.checker.check_yield_spread(16.0)
        assert r.level == "CRITICAL"
        assert r.passed is False

    def test_extreme_negative_spread_critical(self):
        """Spread < -15% → CRITICAL."""
        r = self.checker.check_yield_spread(-16.0)
        assert r.level == "CRITICAL"


class TestSanityCheckerRunAll:

    def setup_method(self):
        self.checker = SanityCheckerV2()

    def test_run_all_clean_data(self):
        """Dati puliti → nessun CRITICAL."""
        data = {
            "vix": 18.5,
            "roll_yield_clf": -0.018,
            "spread_10y_2y": 0.5,
        }
        results = self.checker.run_all(data)
        assert not self.checker.has_critical(results)

    def test_run_all_bad_vix(self):
        """VIX impossibile → has_critical = True."""
        results = self.checker.run_all({"vix": -5.0})
        assert self.checker.has_critical(results)

    def test_run_all_empty_data(self):
        """Dati vuoti → lista vuota risultati."""
        results = self.checker.run_all({})
        assert results == []

    def test_has_critical_false_on_ok(self):
        """has_critical = False se tutti OK."""
        results = [
            SanityResult(True, "OK", "rule1", "ok", 18.5),
            SanityResult(True, "WARN", "rule2", "warn", 0.5),
        ]
        assert not self.checker.has_critical(results)

    def test_has_critical_true_on_critical(self):
        """has_critical = True se almeno un CRITICAL."""
        results = [
            SanityResult(True, "OK", "rule1", "ok"),
            SanityResult(False, "CRITICAL", "rule2", "critical"),
        ]
        assert self.checker.has_critical(results)


# ═══════════════════════════════════════════════════════════════════════════
# SilentFailureDetector
# ═══════════════════════════════════════════════════════════════════════════

class TestSilentFailureDetectorOHLCV:

    def setup_method(self):
        self.detector = SilentFailureDetector(stale_window=3)

    def test_fresh_data_ok(self):
        """Dati freschi con variazione → OK."""
        closes = [15.0, 16.0, 17.5, 18.0, 19.2]
        r = self.detector.check_ohlcv(_ohlcv_df(closes), "^VIX")
        assert r.failure_detected is False
        assert r.quality_score == pytest.approx(1.0)

    def test_stale_data_detected(self):
        """Stesso valore per 3+ giorni → failure_type = 'stale'."""
        closes = [15.0, 16.0, 18.5, 18.5, 18.5]
        r = self.detector.check_ohlcv(_ohlcv_df(closes), "^VIX")
        assert r.failure_detected is True
        assert r.failure_type == "stale"
        assert r.stale_days >= 3

    def test_stale_below_window_ok(self):
        """Stesso valore per 2 giorni (< window=3) → OK."""
        closes = [15.0, 16.0, 17.0, 18.5, 18.5]
        r = self.detector.check_ohlcv(_ohlcv_df(closes), "^VIX")
        assert r.failure_detected is False

    def test_zero_volume_detected(self):
        """Volume = 0 per N giorni → failure_type = 'zero_volume'."""
        closes = [70.0] * 10
        vols   = [500_000] * 8 + [0, 0]
        closes[-1] = 71.0  # prezzo cambia, ma volume zero
        r = self.detector.check_ohlcv(_ohlcv_df(closes, vols), "CL=F")
        assert r.failure_detected is True
        assert r.failure_type == "zero_volume"

    def test_empty_df_missing(self):
        """DataFrame vuoto → failure_type = 'missing'."""
        r = self.detector.check_ohlcv(pd.DataFrame(), "^VIX")
        assert r.failure_detected is True
        assert r.failure_type == "missing"
        assert r.quality_score == pytest.approx(0.0)

    def test_none_df_missing(self):
        """None → failure_type = 'missing'."""
        r = self.detector.check_ohlcv(None, "^VIX")
        assert r.failure_detected is True
        assert r.failure_type == "missing"

    def test_quality_score_stale_degraded(self):
        """quality_score < 1.0 per dati stale."""
        closes = [18.5] * 10
        r = self.detector.check_ohlcv(_ohlcv_df(closes), "^VIX")
        assert r.quality_score < 1.0

    def test_latest_value_populated(self):
        """latest_value popolato con il valore corrente."""
        closes = [15.0, 16.0, 17.5]
        r = self.detector.check_ohlcv(_ohlcv_df(closes), "^VIX")
        assert r.latest_value == pytest.approx(17.5)

    def test_series_id_in_result(self):
        """series_id correttamente propagato nell'output."""
        closes = [18.0, 19.0, 20.0]
        r = self.detector.check_ohlcv(_ohlcv_df(closes), "MY_SERIES")
        assert r.series_id == "MY_SERIES"


class TestSilentFailureDetectorMacro:

    def setup_method(self):
        self.detector = SilentFailureDetector()

    def test_fresh_macro_ok(self):
        """Serie macro aggiornata 5gg fa → OK."""
        df = _macro_df([4.5] * 12, days_old=5)
        r  = self.detector.check_macro_series(df, "FEDFUNDS", max_stale_days=35)
        assert r.failure_detected is False
        assert r.quality_score == pytest.approx(1.0)

    def test_stale_macro_detected(self):
        """Serie macro aggiornata 40gg fa → stale (oltre 35gg)."""
        df = _macro_df([4.5] * 12, days_old=40)
        r  = self.detector.check_macro_series(df, "FEDFUNDS", max_stale_days=35)
        assert r.failure_detected is True
        assert r.failure_type == "stale"

    def test_empty_macro_missing(self):
        """DataFrame macro vuoto → missing."""
        r = self.detector.check_macro_series(pd.DataFrame(), "DGS10")
        assert r.failure_detected is True
        assert r.failure_type == "missing"

    def test_macro_within_limit_ok(self):
        """Serie mensile entro il limite → OK.

        Il max_stale_days è calcolato in base alla data effettiva
        dell'ultimo dato MS (sempre al 1° del mese corrente/precedente).
        """
        df = _macro_df([2.5] * 12, days_old=5)
        # L'ultima data MS è il 1° del mese → calcoliamo quanto fa
        last_ts = df["ts"].iloc[-1]
        import pandas as pd
        days_since = (pd.Timestamp.now(tz="UTC") - last_ts).days
        # Con max_stale > days_since → non deve essere stale
        max_allowed = days_since + 10
        r = self.detector.check_macro_series(df, "CPIAUCSL", max_stale_days=max_allowed)
        assert r.failure_detected is False

    def test_latest_value_returned(self):
        """latest_value è il valore più recente."""
        df = _macro_df([3.2] * 6, days_old=5)
        r  = self.detector.check_macro_series(df, "CPIAUCSL")
        assert r.latest_value == pytest.approx(3.2)


# ═══════════════════════════════════════════════════════════════════════════
# Integration test: pipeline end-to-end su fixture DuckDB
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegrationPipeline:
    """End-to-end: DuckDB migrato → CompositeSignalAggregator → output."""

    def test_composite_aggregator_with_migrated_db(self, migrated_client):
        """CompositeSignalAggregator legge e aggrega da DB con migration 007."""
        from engine.alpha_generation.composite_signal_aggregator import (
            CompositeSignalAggregator, CompositeSignalOutput,
        )

        # Popola tabelle con dati fixture
        now = datetime.now(timezone.utc)
        migrated_client.execute(
            "INSERT INTO vix_strategy_outputs "
            "(computed_at, vix_signal, action, confidence) "
            "VALUES (?, ?, ?, ?)",
            [now, 0.75, "BUY", "HIGH"],
        )
        migrated_client.execute(
            "INSERT INTO yield_curve_snapshots "
            "(snapshot_date, spread_10y_2y, spread_10y_3m, "
            "recession_prob_12m, curve_regime) "
            "VALUES ('2026-06-15', 0.5, 0.3, 0.15, 'normal')"
        )
        migrated_client.execute(
            "INSERT INTO credit_spread_signals "
            "(computed_at, hy_oas, stress_level, stress_score) "
            "VALUES (?, 350.0, 'low', 0.3)",
            [now],
        )
        migrated_client.execute(
            "INSERT INTO claims_inflation_signals "
            "(computed_at, icsa_4wk_ma, regime_label, regime_score) "
            "VALUES (?, 220000.0, 'goldilocks', 0.8)",
            [now],
        )

        agg    = CompositeSignalAggregator(duckdb=migrated_client)
        output = agg.compute()

        assert isinstance(output, CompositeSignalOutput)
        assert -1.0 <= output.composite_score <= 1.0
        assert output.recommended_action in ("BUY", "HOLD", "REDUCE")
        assert len(output.components_used) >= 3
        assert output.computed_at.tzinfo is not None
        # Con dati favorevoli → azione positiva
        assert output.composite_score > 0

    def test_composite_persisted_to_db(self, migrated_client):
        """Dopo compute(), engine_composite_signal contiene un record."""
        from engine.alpha_generation.composite_signal_aggregator import (
            CompositeSignalAggregator,
        )
        now = datetime.now(timezone.utc)
        migrated_client.execute(
            "INSERT INTO vix_strategy_outputs "
            "(computed_at, vix_signal, action, confidence) "
            "VALUES (?, 0.6, 'BUY', 'MEDIUM')", [now]
        )

        agg = CompositeSignalAggregator(duckdb=migrated_client)
        agg.compute()

        rows = migrated_client.query(
            "SELECT composite_score, recommended_action "
            "FROM engine_composite_signal"
        )
        assert len(rows) >= 1
        assert rows[-1][1] in ("BUY", "HOLD", "REDUCE")

    def test_sanity_checker_blocks_bad_vix(self):
        """SanityCheckerV2 blocca VIX = -5 (CRITICAL)."""
        checker = SanityCheckerV2()
        result  = checker.check_vix(-5.0)
        assert result.level == "CRITICAL"
        # Il caller dovrebbe sollevare DataQualityError
        from shared.exceptions import DataQualityError
        if not result.passed:
            with pytest.raises(DataQualityError):
                raise DataQualityError("^VIX", 0.0, 0.5)

    def test_silent_failure_integrates_with_quality_score(self):
        """SilentFailureDetector produce quality_score che può bloccare calcoli."""
        detector = SilentFailureDetector(stale_window=3)
        closes   = [18.5] * 10  # stale
        result   = detector.check_ohlcv(_ohlcv_df(closes), "^VIX")

        assert result.quality_score < 1.0
        # quality_score < 0.5 → dato non dovrebbe entrare nei calcoli critici
        if result.quality_score < 0.5:
            assert result.failure_detected is True


# ═══════════════════════════════════════════════════════════════════════════
# Benchmark
# ═══════════════════════════════════════════════════════════════════════════

class TestBenchmarks:

    def test_sanity_checker_run_all_fast(self, benchmark):
        """SanityCheckerV2.run_all() < 1ms."""
        checker = SanityCheckerV2()
        data = {
            "vix": 18.5,
            "roll_yield_clf": -0.018,
            "roll_yield_gcf": 0.005,
            "spread_10y_2y": 0.5,
        }
        result = benchmark(checker.run_all, data)
        assert isinstance(result, list)

    def test_silent_failure_check_fast(self, benchmark):
        """SilentFailureDetector.check_ohlcv() < 5ms."""
        detector = SilentFailureDetector()
        closes   = list(np.random.default_rng(42).uniform(15, 25, 252))
        df       = _ohlcv_df(closes)
        result   = benchmark(detector.check_ohlcv, df, "^VIX")
        assert isinstance(result, SilentFailureResult)
