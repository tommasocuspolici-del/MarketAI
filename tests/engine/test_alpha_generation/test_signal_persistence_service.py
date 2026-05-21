"""Tests SignalPersistenceService — disk-backed cache for composite signal."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, call

import pytest

from engine.alpha_generation.composite_signal_aggregator import CompositeSignalOutput
from engine.alpha_generation.signal_persistence_service import SignalPersistenceService


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_output(
    score: float = 0.4,
    action: str = "BUY",
    confidence: str = "HIGH",
    computed_at: datetime | None = None,
    is_degraded: bool = False,
) -> CompositeSignalOutput:
    return CompositeSignalOutput(
        computed_at=computed_at or datetime.now(UTC),
        composite_score=score,
        recommended_action=action,
        confidence=confidence,
        vix_component=0.1,
        macro_component=0.2,
        yield_curve_component=0.05,
        credit_component=0.03,
        claims_component=0.02,
        labour_market_component=0.0,
        surprise_component=0.0,
        valuation_component=0.0,
        correlation_component=0.0,
        components_used=["vix", "macro"],
        regime="bull",
        credit_stress="low",
        claims_regime="expansion",
        yield_curve_regime="normal",
        breakdown_json='{"vix": 0.1}',
        is_degraded=is_degraded,
    )


def _make_db_row(computed_at=None, score=0.4, action="BUY", confidence="HIGH"):
    computed_at = computed_at or datetime.now(UTC)
    return (
        computed_at,   # computed_at
        0.1,           # vix_component
        0.2,           # macro_component
        0.05,          # yield_curve_component
        0.03,          # credit_component
        0.02,          # claims_component
        score,         # composite_score
        action,        # recommended_action
        confidence,    # confidence
        '{"vix": 0.1}', # breakdown_json
        '{}',          # weights_used_json
        "bull",        # regime
        "low",         # credit_stress
        "expansion",   # claims_regime
        "normal",      # yield_curve_regime
    )


@pytest.fixture()
def mock_db():
    db = MagicMock()
    db.query.return_value = []
    db.execute.return_value = None
    return db


@pytest.fixture()
def svc(mock_db):
    return SignalPersistenceService(duckdb=mock_db)


# ─── Init ─────────────────────────────────────────────────────────────────────

class TestInit:
    def test_stores_db(self, mock_db):
        s = SignalPersistenceService(duckdb=mock_db)
        assert s._db is mock_db


# ─── load_latest ──────────────────────────────────────────────────────────────

class TestLoadLatest:
    def test_returns_none_when_no_db_rows(self, svc):
        result = svc.load_latest()
        assert result is None

    def test_returns_output_when_fresh_row(self, mock_db):
        mock_db.query.return_value = [_make_db_row()]
        s = SignalPersistenceService(duckdb=mock_db)
        result = s.load_latest(max_age_hours=1)
        assert result is not None
        assert isinstance(result, CompositeSignalOutput)

    def test_returns_correct_score(self, mock_db):
        mock_db.query.return_value = [_make_db_row(score=0.75, action="BUY")]
        s = SignalPersistenceService(duckdb=mock_db)
        result = s.load_latest()
        assert result.composite_score == pytest.approx(0.75)
        assert result.recommended_action == "BUY"

    def test_returns_none_on_db_error(self, mock_db):
        mock_db.query.side_effect = Exception("DB unavailable")
        s = SignalPersistenceService(duckdb=mock_db)
        result = s.load_latest()
        assert result is None

    def test_passes_max_age_cutoff_to_query(self, mock_db):
        mock_db.query.return_value = []
        s = SignalPersistenceService(duckdb=mock_db)
        s.load_latest(max_age_hours=2)
        assert mock_db.query.called
        # Il cutoff passato deve essere circa 2h fa
        args = mock_db.query.call_args[0]
        cutoff = args[1][0]
        expected_cutoff = datetime.now(UTC) - timedelta(hours=2)
        diff = abs((cutoff - expected_cutoff).total_seconds())
        assert diff < 5  # tolleranza 5 secondi

    def test_tz_naive_timestamp_handled(self, mock_db):
        # Simula un timestamp tz-naive dal DB (DuckDB può restituirlo senza tz)
        ts_naive = datetime.now()  # no tz
        mock_db.query.return_value = [_make_db_row(computed_at=ts_naive)]
        s = SignalPersistenceService(duckdb=mock_db)
        result = s.load_latest()
        assert result is not None
        assert result.computed_at.tzinfo is not None  # deve essere UTC-aware

    def test_string_timestamp_handled(self, mock_db):
        ts_str = "2026-05-21T10:00:00+00:00"
        mock_db.query.return_value = [_make_db_row(computed_at=ts_str)]
        s = SignalPersistenceService(duckdb=mock_db)
        result = s.load_latest()
        assert result is not None


# ─── persist ──────────────────────────────────────────────────────────────────

class TestPersist:
    def test_calls_execute(self, svc, mock_db):
        svc.persist(_make_output())
        assert mock_db.execute.called

    def test_persist_composite_and_snapshots(self, svc, mock_db):
        svc.persist(_make_output())
        # Almeno 2 chiamate: 1 per engine_composite_signal + N per signal_snapshots
        assert mock_db.execute.call_count >= 2

    def test_no_crash_on_db_error(self, mock_db):
        mock_db.execute.side_effect = Exception("DB write failed")
        s = SignalPersistenceService(duckdb=mock_db)
        # Non deve rilanciare — error_policy RECOVER
        s.persist(_make_output())

    def test_persists_score_in_query(self, svc, mock_db):
        output = _make_output(score=0.55)
        svc.persist(output)
        # Verifica che il composite_score sia passato come argomento
        all_calls_args = [str(c) for c in mock_db.execute.call_args_list]
        assert any("0.55" in a for a in all_calls_args)

    def test_degraded_signal_writes_degraded_quality_flag(self, svc, mock_db):
        output = _make_output(is_degraded=True)
        svc.persist(output)
        all_calls_args = [str(c) for c in mock_db.execute.call_args_list]
        assert any("degraded" in a for a in all_calls_args)

    def test_ok_signal_writes_ok_quality_flag(self, svc, mock_db):
        output = _make_output(is_degraded=False)
        svc.persist(output)
        all_calls_args = [str(c) for c in mock_db.execute.call_args_list]
        assert any("'ok'" in a for a in all_calls_args)


# ─── round-trip ───────────────────────────────────────────────────────────────

class TestRoundTrip:
    def test_persist_then_load(self, mock_db):
        """Simula persist + load successivo dalla stessa sessione DB."""
        output = _make_output(score=0.42, action="BUY", confidence="HIGH")

        # Dopo persist, il DB restituirà la riga appena scritta
        mock_db.query.return_value = [_make_db_row(
            computed_at=output.computed_at,
            score=0.42,
            action="BUY",
            confidence="HIGH",
        )]

        s = SignalPersistenceService(duckdb=mock_db)
        s.persist(output)
        loaded = s.load_latest()

        assert loaded is not None
        assert loaded.composite_score == pytest.approx(0.42)
        assert loaded.recommended_action == "BUY"
        assert loaded.confidence == "HIGH"
