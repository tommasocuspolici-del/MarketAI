"""Tests per CompositeSignalAggregatorV3.

Roadmap v3.0 — Settimana 7.

Verifica:
  · Pesi v3 sommano a 1.00 (invariante critico)
  · _read_pattern_component(): BULLISH→positivo, BEARISH→negativo, NEUTRAL→0
  · compute() integra la componente pattern correttamente
  · Graceful degradation se nessun pattern disponibile
  · Score v3 differisce da v2 quando il pattern è significativo
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import duckdb
import numpy as np
import pytest

from engine.analytics.composite_signal_v3 import (
    CompositeSignalAggregatorV3,
    CompositeSignalOutputV3,
    _WEIGHTS_V3,
)


# ─── Fixture DuckDB in-memory ────────────────────────────────────────────────

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS pattern_signals (
    signal_id     VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    ticker        VARCHAR NOT NULL,
    pattern_type  VARCHAR NOT NULL,
    signal_dir    VARCHAR NOT NULL,
    confidence    DOUBLE NOT NULL,
    start_date    TIMESTAMPTZ,
    end_date      TIMESTAMPTZ,
    start_idx     INTEGER,
    end_idx       INTEGER,
    key_levels_json VARCHAR,
    description   VARCHAR,
    detected_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status        VARCHAR NOT NULL DEFAULT 'ACTIVE'
);
CREATE TABLE IF NOT EXISTS engine_composite_signal (
    computed_at             TIMESTAMPTZ PRIMARY KEY,
    composite_score         DOUBLE,
    recommended_action      VARCHAR,
    confidence              VARCHAR,
    regime                  VARCHAR,
    credit_stress           VARCHAR,
    claims_regime           VARCHAR,
    yield_curve_regime      VARCHAR,
    component_breakdown_json VARCHAR,
    vix_component           DOUBLE,
    macro_component         DOUBLE,
    yield_curve_component   DOUBLE,
    credit_component        DOUBLE,
    claims_component        DOUBLE
);
"""


@pytest.fixture
def conn():
    """Connessione DuckDB in-memory con tabelle necessarie."""
    c = duckdb.connect(":memory:")
    for stmt in _CREATE_TABLES.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            c.execute(stmt)
    return c


def _make_duckdb_mock(conn_fixture):
    """Crea un mock DuckDBClient che usa la connessione in-memory."""
    client = MagicMock()

    @contextmanager
    def _transaction():
        yield conn_fixture

    client.transaction = _transaction

    def _query(sql, params=None):
        if params:
            return conn_fixture.execute(sql, params).fetchall()
        return conn_fixture.execute(sql).fetchall()

    def _execute(sql, params=None):
        if params:
            conn_fixture.execute(sql, params)
        else:
            conn_fixture.execute(sql)

    client.query = _query
    client.execute = _execute
    return client


def _insert_pattern(conn_fixture, signal_dir: str, confidence: float,
                    pattern_type: str = "double_top",
                    days_ago: int = 1,
                    status: str = "ACTIVE") -> None:
    """Helper: inserisce un pattern_signal di test."""
    detected = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    conn_fixture.execute(
        """
        INSERT INTO pattern_signals
        (ticker, pattern_type, signal_dir, confidence, detected_at, status,
         start_date, end_date, start_idx, end_idx)
        VALUES (?, ?, ?, ?, ?::TIMESTAMPTZ, ?, NOW(), NOW(), 0, 10)
        """,
        ["AAPL", pattern_type, signal_dir, confidence, detected, status],
    )


# ─── Test: invariante pesi ────────────────────────────────────────────────────

def test_weights_sum_to_one() -> None:
    """I pesi v3 devono sommare esattamente a 1.0."""
    total = sum(_WEIGHTS_V3.values())
    assert total == pytest.approx(1.0, abs=1e-9), (
        f"_WEIGHTS_V3 somma {total}, atteso 1.0"
    )


def test_weights_all_positive() -> None:
    """Tutti i pesi devono essere positivi."""
    for name, w in _WEIGHTS_V3.items():
        assert w > 0, f"Peso '{name}' non positivo: {w}"


def test_weights_pattern_is_present() -> None:
    """Il peso 'pattern' deve esistere in v3 (nuovo componente)."""
    assert "pattern" in _WEIGHTS_V3


# ─── Test: _read_pattern_component ───────────────────────────────────────────

class TestReadPatternComponent:
    """Tests per la lettura e aggregazione del pattern component."""

    def test_no_patterns_returns_none(self, conn) -> None:
        """Nessun pattern attivo → None, 0, {}."""
        client = _make_duckdb_mock(conn)
        agg = CompositeSignalAggregatorV3(duckdb=client)
        score, n, breakdown = agg._read_pattern_component()
        assert score is None
        assert n == 0
        assert breakdown == {}

    def test_bullish_pattern_returns_positive(self, conn) -> None:
        """Pattern bullish con confidence 0.8 → score positivo."""
        _insert_pattern(conn, "bullish", 0.8, "double_bottom")
        client = _make_duckdb_mock(conn)
        agg = CompositeSignalAggregatorV3(duckdb=client)
        score, n, _ = agg._read_pattern_component()
        assert score is not None
        assert score > 0
        assert n == 1

    def test_bearish_pattern_returns_negative(self, conn) -> None:
        """Pattern bearish con confidence 0.75 → score negativo."""
        _insert_pattern(conn, "bearish", 0.75, "double_top")
        client = _make_duckdb_mock(conn)
        agg = CompositeSignalAggregatorV3(duckdb=client)
        score, n, _ = agg._read_pattern_component()
        assert score is not None
        assert score < 0
        assert n == 1

    def test_neutral_pattern_returns_near_zero(self, conn) -> None:
        """Pattern neutral → score = 0.0."""
        _insert_pattern(conn, "neutral", 0.65, "triangle_symmetric")
        client = _make_duckdb_mock(conn)
        agg = CompositeSignalAggregatorV3(duckdb=client)
        score, n, _ = agg._read_pattern_component()
        assert score == pytest.approx(0.0, abs=1e-6)

    def test_mixed_patterns_average(self, conn) -> None:
        """Pattern bullish + bearish di pari confidence → score ≈ 0."""
        _insert_pattern(conn, "bullish", 0.70, "head_and_shoulders_inv")
        _insert_pattern(conn, "bearish", 0.70, "double_top")
        client = _make_duckdb_mock(conn)
        agg = CompositeSignalAggregatorV3(duckdb=client)
        score, n, _ = agg._read_pattern_component()
        assert score is not None
        assert abs(score) < 0.01   # media cancella il segnale
        assert n == 2

    def test_score_clipped_to_minus_one_plus_one(self, conn) -> None:
        """Score sempre in [-1, 1] anche con molti pattern ad alta confidence."""
        for _ in range(5):
            _insert_pattern(conn, "bullish", 0.95)
        client = _make_duckdb_mock(conn)
        agg = CompositeSignalAggregatorV3(duckdb=client)
        score, _, _ = agg._read_pattern_component()
        assert score is not None
        assert -1.0 <= score <= 1.0

    def test_expired_patterns_excluded(self, conn) -> None:
        """Pattern con status='EXPIRED' NON vengono inclusi nel segnale."""
        _insert_pattern(conn, "bullish", 0.90, status="EXPIRED")
        client = _make_duckdb_mock(conn)
        agg = CompositeSignalAggregatorV3(duckdb=client)
        score, n, _ = agg._read_pattern_component()
        assert n == 0

    def test_old_patterns_excluded_by_lookback(self, conn) -> None:
        """Pattern più vecchi di 7 giorni → esclusi dal lookback."""
        _insert_pattern(conn, "bullish", 0.90, days_ago=10, status="ACTIVE")
        client = _make_duckdb_mock(conn)
        agg = CompositeSignalAggregatorV3(duckdb=client)
        score, n, _ = agg._read_pattern_component()
        assert n == 0


# ─── Test: compute() ─────────────────────────────────────────────────────────

class TestComputeV3:
    """Tests per il metodo compute() completo."""

    def _mock_v2_components(self, agg: CompositeSignalAggregatorV3) -> None:
        """Mocka tutti i lettori di componenti v2 per isolare il test v3."""
        agg._read_vix_component           = lambda: 0.4   # type: ignore
        agg._read_yield_curve_component   = lambda: (0.2, "normal")  # type: ignore
        agg._read_credit_component        = lambda: (0.1, "low")  # type: ignore
        agg._read_claims_component        = lambda: (0.3, "goldilocks")  # type: ignore
        agg._read_macro_conviction_component = lambda: None  # type: ignore
        agg._read_labour_component        = lambda: 0.2   # type: ignore
        agg._read_surprise_component      = lambda: 0.1   # type: ignore
        agg._read_current_regime          = lambda: "bull"  # type: ignore

    def test_compute_returns_v3_output(self, conn) -> None:
        """compute() ritorna CompositeSignalOutputV3."""
        client = _make_duckdb_mock(conn)
        agg = CompositeSignalAggregatorV3(duckdb=client)
        self._mock_v2_components(agg)
        result = agg.compute()
        assert isinstance(result, CompositeSignalOutputV3)

    def test_composite_score_v3_in_range(self, conn) -> None:
        """composite_score_v3 in [-1, 1]."""
        client = _make_duckdb_mock(conn)
        agg = CompositeSignalAggregatorV3(duckdb=client)
        self._mock_v2_components(agg)
        result = agg.compute()
        assert -1.0 <= result.composite_score_v3 <= 1.0

    def test_bullish_pattern_increases_score(self, conn) -> None:
        """Pattern bullish aumenta il composite score rispetto alla v2."""
        _insert_pattern(conn, "bullish", 0.90)
        client = _make_duckdb_mock(conn)
        agg_with = CompositeSignalAggregatorV3(duckdb=client)
        self._mock_v2_components(agg_with)
        result_with = agg_with.compute()

        # Confronto: senza pattern → score senza componente pattern
        conn.execute("DELETE FROM pattern_signals")
        agg_without = CompositeSignalAggregatorV3(duckdb=client)
        self._mock_v2_components(agg_without)
        result_without = agg_without.compute()

        assert result_with.composite_score_v3 >= result_without.composite_score_v3

    def test_no_patterns_graceful_degradation(self, conn) -> None:
        """Nessun pattern → compute() funziona senza errori, pattern_count=0."""
        client = _make_duckdb_mock(conn)
        agg = CompositeSignalAggregatorV3(duckdb=client)
        self._mock_v2_components(agg)
        result = agg.compute()
        assert result.pattern_count == 0
        assert isinstance(result.composite_score_v3, float)

    def test_action_string_valid(self, conn) -> None:
        """recommended_action_v3 è uno dei valori attesi."""
        client = _make_duckdb_mock(conn)
        agg = CompositeSignalAggregatorV3(duckdb=client)
        self._mock_v2_components(agg)
        result = agg.compute()
        assert result.recommended_action_v3 in ("BUY", "HOLD", "REDUCE")

    def test_breakdown_json_v3_is_valid_json(self, conn) -> None:
        """breakdown_json_v3 è JSON valido."""
        import json
        client = _make_duckdb_mock(conn)
        agg = CompositeSignalAggregatorV3(duckdb=client)
        self._mock_v2_components(agg)
        result = agg.compute()
        parsed = json.loads(result.breakdown_json_v3)
        assert isinstance(parsed, dict)
