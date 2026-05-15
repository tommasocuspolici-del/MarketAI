"""Tests for graceful degradation patterns — ROADMAP_CODE_QUALITY_v1.0, Settimana 6.

Verifica che ogni modulo che fa I/O (DB, yfinance, API eToro) restituisca
uno stato degradato utile invece di crashare o propagare eccezioni non gestite.

DoD:
  □ Ogni modulo che fa I/O ha un test "cosa succede se la sorgente è down"
  □ Tutti i dataclass di output critici hanno classmethod degraded() o empty()
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import duckdb
import pytest

from engine.alpha_generation.composite_signal_aggregator import CompositeSignalOutput
from engine.alpha_generation.schemas import MacroConvictionResult
from engine.market_data.instrument_registry import (
    InstrumentMapping,
    InstrumentRegistry,
    _SEED_FALLBACK,
)
from engine.market_data.live_market_service import MarketSnapshot
from shared.db.duckdb_client import DuckDBClient
from shared.exceptions import DuckDBError


# ─────────────────────────────────────────── MacroConvictionResult

class TestMacroConvictionResultDegraded:
    def test_degraded_classmethod_exists(self):
        assert hasattr(MacroConvictionResult, "degraded")

    def test_degraded_returns_instance(self):
        result = MacroConvictionResult.degraded()
        assert isinstance(result, MacroConvictionResult)

    def test_degraded_has_is_degraded_true(self):
        result = MacroConvictionResult.degraded()
        assert result.is_degraded is True

    def test_degraded_score_is_zero(self):
        result = MacroConvictionResult.degraded()
        assert result.macro_score == 0.0

    def test_degraded_confidence_is_low(self):
        result = MacroConvictionResult.degraded()
        assert result.confidence == "LOW"

    def test_degraded_series_available_is_zero(self):
        result = MacroConvictionResult.degraded()
        assert result.series_available == 0

    def test_normal_result_is_not_degraded(self):
        """Un MacroConvictionResult normale ha is_degraded=False (default)."""
        normal = MacroConvictionResult.degraded()
        # is_degraded è esplicitamente True solo per il classmethod
        assert normal.is_degraded is True
        # Il campo ha default False: non degradato se costruito normalmente
        assert MacroConvictionResult.__dataclass_fields__["is_degraded"].default is False


# ─────────────────────────────────────────── CompositeSignalOutput

class TestCompositeSignalOutputDegraded:
    def test_degraded_classmethod_exists(self):
        assert hasattr(CompositeSignalOutput, "degraded")

    def test_degraded_returns_instance(self):
        result = CompositeSignalOutput.degraded()
        assert isinstance(result, CompositeSignalOutput)

    def test_degraded_has_is_degraded_true(self):
        result = CompositeSignalOutput.degraded()
        assert result.is_degraded is True

    def test_degraded_score_is_zero(self):
        result = CompositeSignalOutput.degraded()
        assert result.composite_score == 0.0

    def test_degraded_action_is_hold(self):
        result = CompositeSignalOutput.degraded()
        assert result.recommended_action == "HOLD"

    def test_degraded_components_used_empty(self):
        result = CompositeSignalOutput.degraded()
        assert result.components_used == []

    def test_degraded_error_reason_in_breakdown(self):
        result = CompositeSignalOutput.degraded(error_reason="db_down")
        assert "db_down" in result.breakdown_json

    def test_normal_result_is_not_degraded_by_default(self):
        assert CompositeSignalOutput.__dataclass_fields__["is_degraded"].default is False


# ─────────────────────────────────────────── MarketSnapshot

class TestMarketSnapshotEmpty:
    def test_empty_classmethod_exists(self):
        assert hasattr(MarketSnapshot, "empty")

    def test_empty_returns_instance(self):
        snap = MarketSnapshot.empty()
        assert isinstance(snap, MarketSnapshot)

    def test_empty_is_unavailable_true(self):
        snap = MarketSnapshot.empty()
        assert snap.is_unavailable is True

    def test_empty_kpis_is_empty_list(self):
        snap = MarketSnapshot.empty()
        assert snap.kpis == []

    def test_empty_fetched_at_is_recent(self):
        before = time.time()
        snap = MarketSnapshot.empty()
        assert snap.fetched_at >= before

    def test_normal_snapshot_is_not_unavailable(self):
        snap = MarketSnapshot()
        assert snap.is_unavailable is False

    def test_is_unavailable_field_default_is_false(self):
        snap = MarketSnapshot()
        assert snap.is_unavailable is False


# ─────────────────────────────────────────── InstrumentRegistry seed fallback

class TestInstrumentRegistrySeedFallback:
    @pytest.fixture()
    def failing_client(self) -> DuckDBClient:
        """DuckDBClient che lancia DuckDBError su ogni query."""
        client = MagicMock(spec=DuckDBClient)
        client.query.side_effect = DuckDBError("DB file corrupted")
        return client

    def test_get_falls_back_to_seed_on_db_error(self, failing_client):
        registry = InstrumentRegistry(client=failing_client)
        result = registry.get(3040)
        assert result is not None
        assert result.real_ticker == "SWDA.L"

    def test_get_ticker_falls_back_to_seed_on_db_error(self, failing_client):
        registry = InstrumentRegistry(client=failing_client)
        assert registry.get_ticker(3040) == "SWDA.L"
        assert registry.get_ticker(3434) == "CSPX.L"
        assert registry.get_ticker(15435) == "EIMI.L"
        assert registry.get_ticker(3394) == "EUN5.DE"
        assert registry.get_ticker(10569) == "IBCN.DE"

    def test_get_returns_none_for_unknown_id_when_db_fails(self, failing_client):
        registry = InstrumentRegistry(client=failing_client)
        result = registry.get(99999)
        assert result is None

    def test_seed_fallback_contains_five_instruments(self):
        assert len(_SEED_FALLBACK) == 5

    def test_seed_fallback_instrument_3040_is_swda(self):
        mapping = _SEED_FALLBACK[3040]
        assert mapping.real_ticker == "SWDA.L"
        assert mapping.native_currency == "GBX"
        assert mapping.source == "manual"

    def test_get_logs_error_on_db_failure(self, failing_client, caplog):
        import logging
        registry = InstrumentRegistry(client=failing_client)
        with caplog.at_level(logging.ERROR):
            registry.get(3040)
        assert any("3040" in r.message or "3040" in str(r.args) for r in caplog.records)


# ─────────────────────────────────────────── MacroConvictionCalculator degraded

class TestMacroConvictionCalculatorGracefulDegradation:
    def test_compute_returns_degraded_when_internal_raises(self):
        """Se _compute_internal() lancia un'eccezione, compute() ritorna degraded."""
        from engine.alpha_generation.macro_conviction import MacroConvictionCalculator

        mock_repo = MagicMock()
        calc = MacroConvictionCalculator(macro_repo=mock_repo)
        # Patch _compute_internal per simulare un errore catastrofico (non per-serie)
        with patch.object(calc, "_compute_internal", side_effect=RuntimeError("unexpected internal error")):
            result = calc.compute()
        assert isinstance(result, MacroConvictionResult)
        assert result.is_degraded is True
        assert result.macro_score == 0.0

    def test_compute_returns_low_confidence_when_all_series_missing(self):
        """Con tutte le serie mancanti (per-series exception), il risultato è LOW confidence.

        Nota: i fallimenti per-serie sono già gestiti internamente da _load_all_series().
        Il risultato è valido ma con series_available=0 e confidence=LOW.
        """
        from engine.alpha_generation.macro_conviction import MacroConvictionCalculator

        mock_repo = MagicMock()
        mock_repo.read_macro.side_effect = Exception("DB connection lost per serie")
        calc = MacroConvictionCalculator(macro_repo=mock_repo)
        result = calc.compute()
        assert isinstance(result, MacroConvictionResult)
        assert result.series_available == 0
        assert result.confidence == "LOW"
        # Non degraded perché il calcolo è riuscito (graceful per-series fallback)
        assert result.is_degraded is False

    def test_compute_degraded_does_not_raise(self):
        """compute() non propaga mai eccezioni al chiamante."""
        from engine.alpha_generation.macro_conviction import MacroConvictionCalculator

        mock_repo = MagicMock()
        calc = MacroConvictionCalculator(macro_repo=mock_repo)
        with patch.object(calc, "_compute_internal", side_effect=RuntimeError("unexpected")):
            result = calc.compute()
        assert result is not None


# ─────────────────────────────────────────── LiveMarketService unavailable flag

class TestLiveMarketServiceUnavailableFlag:
    def test_snapshot_is_unavailable_when_yfinance_fails(self):
        """Se yfinance.download lancia OSError, lo snapshot ha is_unavailable=True."""
        from engine.market_data.live_market_service import LiveMarketService

        with patch("engine.market_data.live_market_service.get_live_market_service") as _:
            svc = LiveMarketService.__new__(LiveMarketService)
            svc._cache = MarketSnapshot()
            svc._lock = __import__("threading").Lock()
            svc._refresh_cv = __import__("threading").Condition(svc._lock)
            svc._refresh_in_progress = False
            svc._ws_manager = None
            from personal.data_entry.override_store import ManualOverrideStore
            svc._override_store = ManualOverrideStore.__new__(ManualOverrideStore)
            svc._override_store._overrides = {}

            with patch("yfinance.download", side_effect=OSError("network unreachable")):
                snapshot = svc._fetch_snapshot()

            assert snapshot.is_unavailable is True
