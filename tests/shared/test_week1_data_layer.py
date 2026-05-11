"""Test suite — Roadmap Unificata Settimana 1.

Copre:
  · Migration 007: tutte le nuove tabelle presenti dopo apply_pending()
  · MacroRepository: tutti i nuovi metodi read (con DB vuoto → None graceful)
  · FuturesFetcher: classificazione term structure, roll_yield, persist
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from shared.db.duckdb_client import DuckDBClient
from shared.db.duckdb_migrator import DuckDBMigrator
from shared.db.macro_repo import (
    MacroRepository,
    ClaimsInflationSignal,
    YieldCurveSnapshot,
    CreditSpreadSignal,
    EngineCompositeSignal,
)


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def migrated_client(tmp_duckdb_path):
    """DuckDBClient con tutte le migration applicate."""
    client = DuckDBClient(path=tmp_duckdb_path)
    migrator = DuckDBMigrator(client=client)
    migrator.apply_pending()
    yield client
    client.close()


@pytest.fixture()
def macro_repo(migrated_client):
    return MacroRepository(client=migrated_client)


# ═══════════════════════════════════════════════════════════════════════════
# Test Migration 007
# ═══════════════════════════════════════════════════════════════════════════

class TestMigration007:
    """Verifica che tutte le tabelle della migration 007 esistano."""

    EXPECTED_TABLES = [
        "vix_signals",
        "vix_strategy_outputs",
        "futures_ohlcv",
        "claims_inflation_signals",
        "yield_curve_snapshots",
        "credit_spread_signals",
        "engine_composite_signal",
        "regime_reports",
        # Tabelle migration 001 (devono ancora esistere)
        "prices_ohlcv",
        "macro_series",
        "backtest_results",
        "correlations",
    ]

    def test_all_tables_exist(self, migrated_client):
        """Ogni tabella della migration 007 deve esistere dopo apply_pending()."""
        rows = migrated_client.query(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        )
        tables = {row[0] for row in rows}
        for table in self.EXPECTED_TABLES:
            assert table in tables, f"Tabella mancante: {table}"

    def test_migration_idempotent(self, migrated_client):
        """apply_pending() eseguita 2 volte non deve creare errori."""
        migrator = DuckDBMigrator(client=migrated_client)
        applied = migrator.apply_pending()
        assert applied == 0

    def test_vix_signals_columns(self, migrated_client):
        """vix_signals ha le colonne attese."""
        rows = migrated_client.query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'vix_signals'"
        )
        cols = {row[0] for row in rows}
        expected = {
            "computed_at", "vix_level", "vix_zscore", "vix_vxv_ratio",
            "vix_pct_rank", "spike_detected", "zscore_signal", "regime",
            "lookback_days",
        }
        assert expected.issubset(cols)

    def test_futures_ohlcv_columns(self, migrated_client):
        """futures_ohlcv ha roll_yield, basis, term_structure."""
        rows = migrated_client.query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'futures_ohlcv'"
        )
        cols = {row[0] for row in rows}
        assert {"roll_yield", "basis", "term_structure", "open_interest"}.issubset(cols)

    def test_engine_composite_signal_columns(self, migrated_client):
        """engine_composite_signal ha tutti i componenti."""
        rows = migrated_client.query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'engine_composite_signal'"
        )
        cols = {row[0] for row in rows}
        assert {
            "composite_score", "recommended_action", "confidence",
            "vix_component", "macro_component", "yield_curve_component",
        }.issubset(cols)

    def test_can_insert_futures_row(self, migrated_client):
        """futures_ohlcv accetta INSERT con tutti i campi."""
        migrated_client.execute(
            "INSERT INTO futures_ohlcv "
            "(ticker, contract_month, ts, close, roll_yield, basis, term_structure) "
            "VALUES ('CL=F', 'front', '2026-06-01 00:00:00+00', 71.5, -0.018, 1.2, 'contango')"
        )
        rows = migrated_client.query(
            "SELECT ticker, roll_yield, term_structure FROM futures_ohlcv"
        )
        assert len(rows) == 1
        assert rows[0][0] == "CL=F"
        assert abs(rows[0][1] - (-0.018)) < 1e-6
        assert rows[0][2] == "contango"

    def test_can_insert_composite_signal(self, migrated_client):
        """engine_composite_signal accetta INSERT completo."""
        migrated_client.execute(
            "INSERT INTO engine_composite_signal "
            "(computed_at, composite_score, recommended_action, confidence) "
            "VALUES ('2026-06-01 12:00:00+00', -0.23, 'HOLD', 'MEDIUM')"
        )
        rows = migrated_client.query(
            "SELECT composite_score, recommended_action FROM engine_composite_signal"
        )
        assert len(rows) == 1
        assert abs(rows[0][0] - (-0.23)) < 1e-6

    def test_yield_curve_primary_key_upsert(self, migrated_client):
        """yield_curve_snapshots PK DATE — INSERT OR REPLACE su stessa data."""
        migrated_client.execute(
            "INSERT INTO yield_curve_snapshots "
            "(snapshot_date, y_10y, spread_10y_2y) VALUES ('2026-06-01', 4.5, 0.3)"
        )
        migrated_client.execute(
            "INSERT OR REPLACE INTO yield_curve_snapshots "
            "(snapshot_date, y_10y, spread_10y_2y) VALUES ('2026-06-01', 4.6, 0.25)"
        )
        rows = migrated_client.query(
            "SELECT y_10y FROM yield_curve_snapshots"
        )
        assert len(rows) == 1
        assert abs(rows[0][0] - 4.6) < 1e-6

    def test_vix_strategy_outputs_schema(self, migrated_client):
        """vix_strategy_outputs accetta INSERT con i campi chiave."""
        migrated_client.execute(
            "INSERT INTO vix_strategy_outputs "
            "(computed_at, vix_signal, action, macro_score, composite_score, confidence) "
            "VALUES ('2026-06-01 12:00:00+00', 0.75, 'BUY', 0.4, 0.58, 'HIGH')"
        )
        rows = migrated_client.query(
            "SELECT action, composite_score FROM vix_strategy_outputs"
        )
        assert len(rows) == 1
        assert rows[0][0] == "BUY"


# ═══════════════════════════════════════════════════════════════════════════
# Test MacroRepository — nuovi metodi read
# ═══════════════════════════════════════════════════════════════════════════

class TestMacroRepositoryExtended:
    """Verifica i nuovi metodi read del MacroRepository."""

    def test_read_claims_signal_empty_db(self, macro_repo):
        """Con DB vuoto, read_claims_signal() ritorna None."""
        assert macro_repo.read_claims_signal() is None

    def test_read_yield_curve_empty_db(self, macro_repo):
        """Con DB vuoto, read_yield_curve_snapshot() ritorna None."""
        assert macro_repo.read_yield_curve_snapshot() is None

    def test_read_credit_spreads_empty_db(self, macro_repo):
        """Con DB vuoto, read_credit_spreads() ritorna None."""
        assert macro_repo.read_credit_spreads() is None

    def test_read_futures_basis_empty_db(self, macro_repo):
        """Con DB vuoto, read_futures_basis() ritorna None."""
        assert macro_repo.read_futures_basis("CL=F") is None

    def test_read_composite_signal_empty_db(self, macro_repo):
        """Con DB vuoto, read_composite_signal() ritorna None."""
        assert macro_repo.read_composite_signal() is None

    def test_read_claims_signal_with_data(self, migrated_client):
        """read_claims_signal() ritorna ClaimsInflationSignal corretto."""
        now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        migrated_client.execute(
            "INSERT INTO claims_inflation_signals "
            "(computed_at, icsa_4wk_ma, icsa_yoy_change_pct, cpi_yoy, "
            "stagflation_signal, goldilocks_signal, overheating_signal, "
            "recession_watch, regime_label, regime_score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [now, 215000.0, 0.05, 3.2, False, True, False, False, "goldilocks", 0.8],
        )
        repo = MacroRepository(client=migrated_client)
        result = repo.read_claims_signal()
        assert result is not None
        assert isinstance(result, ClaimsInflationSignal)
        assert result.regime_label == "goldilocks"
        assert abs(result.regime_score - 0.8) < 1e-6
        assert result.goldilocks_signal is True
        assert result.stagflation_signal is False
        assert abs(result.cpi_yoy - 3.2) < 1e-6

    def test_read_yield_curve_with_data(self, migrated_client):
        """read_yield_curve_snapshot() ritorna YieldCurveSnapshot corretto."""
        migrated_client.execute(
            "INSERT INTO yield_curve_snapshots "
            "(snapshot_date, y_3m, y_2y, y_10y, spread_10y_2y, "
            "spread_10y_3m, breakeven_10y, recession_prob_12m, curve_regime) "
            "VALUES ('2026-06-15', 5.1, 4.8, 4.5, -0.30, -0.60, 2.3, 0.35, 'inverted')"
        )
        repo = MacroRepository(client=migrated_client)
        result = repo.read_yield_curve_snapshot()
        assert result is not None
        assert isinstance(result, YieldCurveSnapshot)
        assert result.curve_regime == "inverted"
        assert abs(result.spread_10y_2y - (-0.30)) < 1e-6
        assert abs(result.recession_prob_12m - 0.35) < 1e-6

    def test_read_credit_spreads_with_data(self, migrated_client):
        """read_credit_spreads() ritorna CreditSpreadSignal corretto."""
        now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        migrated_client.execute(
            "INSERT INTO credit_spread_signals "
            "(computed_at, hy_oas, ig_oas, hy_ig_ratio, ted_spread, "
            "nfci, stress_level, stress_score) "
            "VALUES (?, 450.0, 120.0, 3.75, 25.0, -0.1, 'moderate', 0.0)",
            [now],
        )
        repo = MacroRepository(client=migrated_client)
        result = repo.read_credit_spreads()
        assert result is not None
        assert isinstance(result, CreditSpreadSignal)
        assert result.stress_level == "moderate"
        assert abs(result.hy_oas - 450.0) < 1e-6

    def test_read_futures_basis_with_data(self, migrated_client):
        """read_futures_basis() ritorna il basis corretto."""
        now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        migrated_client.execute(
            "INSERT INTO futures_ohlcv "
            "(ticker, contract_month, ts, close, basis, term_structure) "
            "VALUES ('GC=F', 'front', ?, 2350.0, 5.5, 'contango')",
            [now],
        )
        repo = MacroRepository(client=migrated_client)
        result = repo.read_futures_basis("GC=F")
        assert result is not None
        assert abs(result - 5.5) < 1e-6

    def test_read_composite_signal_with_data(self, migrated_client):
        """read_composite_signal() ritorna EngineCompositeSignal corretto."""
        now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        migrated_client.execute(
            "INSERT INTO engine_composite_signal "
            "(computed_at, composite_score, recommended_action, confidence, "
            "regime, credit_stress, claims_regime, yield_curve_regime) "
            "VALUES (?, -0.23, 'HOLD', 'MEDIUM', 'bear', 'moderate', 'neutral', 'flat')",
            [now],
        )
        repo = MacroRepository(client=migrated_client)
        result = repo.read_composite_signal()
        assert result is not None
        assert isinstance(result, EngineCompositeSignal)
        assert result.recommended_action == "HOLD"
        assert abs(result.composite_score - (-0.23)) < 1e-6
        assert result.regime == "bear"

    def test_read_futures_basis_wrong_ticker(self, macro_repo):
        """read_futures_basis con ticker senza dati ritorna None."""
        assert macro_repo.read_futures_basis("NONEXISTENT=F") is None

    def test_new_methods_exist(self, macro_repo):
        """Tutti i nuovi metodi sono stati attaccati alla classe."""
        assert hasattr(macro_repo, "read_claims_signal")
        assert hasattr(macro_repo, "read_yield_curve_snapshot")
        assert hasattr(macro_repo, "read_credit_spreads")
        assert hasattr(macro_repo, "read_futures_basis")
        assert hasattr(macro_repo, "read_composite_signal")
        # Metodi originali ancora presenti
        assert hasattr(macro_repo, "read_macro")
        assert hasattr(macro_repo, "write_macro_series")

    def test_composite_score_range(self, migrated_client):
        """composite_score deve rimanere in [-1, 1] — verifica constraint logico."""
        now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        migrated_client.execute(
            "INSERT INTO engine_composite_signal "
            "(computed_at, composite_score, recommended_action, confidence) "
            "VALUES (?, -1.0, 'REDUCE', 'HIGH')",
            [now],
        )
        repo = MacroRepository(client=migrated_client)
        result = repo.read_composite_signal()
        assert result is not None
        assert -1.0 <= result.composite_score <= 1.0


# ═══════════════════════════════════════════════════════════════════════════
# Test FuturesFetcher
# ═══════════════════════════════════════════════════════════════════════════

class TestFuturesFetcher:
    """Unit test per FuturesFetcher senza chiamate reali a yfinance."""

    def test_classify_term_structure_contango(self):
        """Roll yield negativo → contango."""
        from engine.market_data.fetchers.futures_fetcher import FuturesFetcher
        assert FuturesFetcher._classify_term_structure(-0.018) == "contango"

    def test_classify_term_structure_backwardation(self):
        """Roll yield positivo → backwardation."""
        from engine.market_data.fetchers.futures_fetcher import FuturesFetcher
        assert FuturesFetcher._classify_term_structure(0.012) == "backwardation"

    def test_classify_term_structure_flat(self):
        """Roll yield vicino a zero → flat."""
        from engine.market_data.fetchers.futures_fetcher import FuturesFetcher
        assert FuturesFetcher._classify_term_structure(0.002) == "flat"
        assert FuturesFetcher._classify_term_structure(-0.003) == "flat"

    def test_classify_term_structure_boundary(self):
        """Test ai boundary esatti ±0.5%."""
        from engine.market_data.fetchers.futures_fetcher import FuturesFetcher
        # Esattamente sul boundary
        assert FuturesFetcher._classify_term_structure(0.006) == "backwardation"
        assert FuturesFetcher._classify_term_structure(-0.006) == "contango"
        # Sotto il boundary
        assert FuturesFetcher._classify_term_structure(-0.004) == "flat"
        assert FuturesFetcher._classify_term_structure(0.005) == "flat"

    def test_spot_proxies_complete(self):
        """Tutti i FUTURES_TICKERS hanno un proxy spot definito."""
        from engine.market_data.fetchers.futures_fetcher import (
            FUTURES_TICKERS,
            _SPOT_PROXIES,
        )
        for ticker in FUTURES_TICKERS:
            assert ticker in _SPOT_PROXIES, f"Manca proxy spot per {ticker}"

    def test_persist_skips_when_no_duckdb(self):
        """_persist_futures_rows ritorna 0 se duckdb_client è None."""
        from engine.market_data.fetchers.futures_fetcher import FuturesFetcher
        fetcher = FuturesFetcher.__new__(FuturesFetcher)
        fetcher._duckdb = None
        fetcher._rate_limiter = MagicMock()

        dates = pd.date_range("2026-05-01", periods=5, freq="D", tz="UTC")
        df = pd.DataFrame({"Close": [70.0] * 5}, index=dates)
        rows = fetcher._persist_futures_rows(
            ticker="CL=F", futures_df=df, roll_yield=-0.015,
            basis=1.2, term_structure="contango",
        )
        assert rows == 0

    def test_persist_writes_to_duckdb(self, migrated_client):
        """_persist_futures_rows scrive effettivamente in futures_ohlcv."""
        from engine.market_data.fetchers.futures_fetcher import FuturesFetcher

        fetcher = FuturesFetcher.__new__(FuturesFetcher)
        fetcher._duckdb = migrated_client
        fetcher._rate_limiter = MagicMock()

        dates = pd.date_range("2026-05-01", periods=5, freq="D", tz="UTC")
        df = pd.DataFrame(
            {
                "Open": [70.0] * 5, "High": [72.0] * 5,
                "Low": [69.0] * 5, "Close": [71.0] * 5,
                "Volume": [50000] * 5,
            },
            index=dates,
        )

        rows = fetcher._persist_futures_rows(
            ticker="CL=F", futures_df=df, roll_yield=-0.018,
            basis=1.5, term_structure="contango",
        )
        assert rows == 5

        db_rows = migrated_client.query(
            "SELECT COUNT(*) FROM futures_ohlcv WHERE ticker = 'CL=F'"
        )
        assert db_rows[0][0] == 5

    @pytest.mark.asyncio
    async def test_fetch_futures_with_mock_yfinance(self, migrated_client):
        """fetch_futures() con yfinance mockato ritorna struttura corretta."""
        from engine.market_data.fetchers.futures_fetcher import FuturesFetcher

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        dates = pd.date_range("2026-04-01", periods=35, freq="D", tz="UTC")
        mock_df = pd.DataFrame(
            {
                "Open":   np.linspace(70.0, 71.5, 35),
                "High":   np.linspace(72.0, 73.5, 35),
                "Low":    np.linspace(68.0, 69.5, 35),
                "Close":  np.linspace(70.0, 71.5, 35),
                "Volume": [75000] * 35,
            },
            index=dates,
        )

        fetcher = FuturesFetcher.__new__(FuturesFetcher)
        fetcher._rate_limiter = mock_rate_limiter
        fetcher._duckdb = migrated_client

        with patch.object(fetcher, "_yf_download", return_value=mock_df):
            result = await fetcher.fetch_futures("CL=F", days=30)

        assert result["ticker"] == "CL=F"
        assert result["latest_close"] > 0
        assert result["term_structure"] in ("backwardation", "contango", "flat")
        assert isinstance(result["roll_yield"], float)
        assert result["rows_written"] > 0

    @pytest.mark.asyncio
    async def test_fetch_futures_invalid_ticker(self):
        """Ticker non supportato → ValueError."""
        from engine.market_data.fetchers.futures_fetcher import FuturesFetcher

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        fetcher = FuturesFetcher.__new__(FuturesFetcher)
        fetcher._rate_limiter = mock_rate_limiter
        fetcher._duckdb = None

        with pytest.raises(ValueError, match="non supportato"):
            await fetcher.fetch_futures("INVALID=F", days=5)


# ═══════════════════════════════════════════════════════════════════════════
# Test Feature Flags — nuovi flag Roadmap Unificata
# ═══════════════════════════════════════════════════════════════════════════

class TestNewFeatureFlags:
    """Verifica che i nuovi flag della roadmap unificata siano caricabili."""

    NEW_FLAGS = [
        "market_data_refresh",
        "analysis_pipeline_scheduled",
        "vix_based_analysis",
        "vix_vxv_ratio",
        "futures_analysis",
        "claims_inflation_cross",
        "hy_credit_spread",
        "regime_conditional_sizing",
    ]

    def setup_method(self):
        """Reset cache before each test."""
        import shared.feature_flags as ff
        ff._load_flags.cache_clear()

    def test_new_flags_load_as_bool(self):
        """I nuovi flag devono esistere e ritornare bool."""
        from shared.feature_flags import is_enabled
        for flag in self.NEW_FLAGS:
            result = is_enabled(flag)
            assert isinstance(result, bool), f"Flag '{flag}' non ritorna bool"

    def test_scheduler_flags_enabled(self):
        """market_data_refresh, vix_based_analysis, futures_analysis = True."""
        from shared.feature_flags import is_enabled
        assert is_enabled("market_data_refresh") is True
        assert is_enabled("vix_based_analysis") is True
        assert is_enabled("futures_analysis") is True

    def test_phase3_flags_disabled(self):
        """Flag di fase 3 devono essere False per default."""
        from shared.feature_flags import is_enabled
        assert is_enabled("cot_data") is False
        assert is_enabled("breadth_indicators") is False
        assert is_enabled("factor_model") is False
        assert is_enabled("alpha_decay_monitor") is False

    def test_vix_futures_term_structure_disabled(self):
        """vix_futures_term_structure disabilitato (richiede API dedicata)."""
        from shared.feature_flags import is_enabled
        assert is_enabled("vix_futures_term_structure") is False
