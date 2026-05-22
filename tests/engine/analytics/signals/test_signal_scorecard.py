"""Tests for SignalScorecard — DuckDB persistence of signal quality metrics."""
from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch, call

import duckdb
import pandas as pd
import pytest

from engine.analytics.signals.ic_calculator import ICResult
from engine.analytics.signals.signal_scorecard import ScorecardEntry, SignalScorecard


# ── In-memory DuckDB fixture ───────────────────────────────────────────────────

class _InMemoryDuckDB:
    """Thin wrapper around duckdb.connect(':memory:') that mimics DuckDBClient interface."""

    def __init__(self) -> None:
        self._conn = duckdb.connect(":memory:")

    def execute(self, sql: str, params: list | tuple | None = None) -> duckdb.DuckDBPyConnection:
        if params is not None:
            return self._conn.execute(sql, params)
        return self._conn.execute(sql)

    def query(self, sql: str, params: list | tuple | None = None) -> list[tuple]:
        if params is not None:
            return list(self._conn.execute(sql, params).fetchall())
        return list(self._conn.execute(sql).fetchall())

    def query_df(self, sql: str, params: list | tuple | None = None) -> pd.DataFrame:
        if params is not None:
            return self._conn.execute(sql, params).df()
        return self._conn.execute(sql).df()


@pytest.fixture
def db() -> _InMemoryDuckDB:
    return _InMemoryDuckDB()


@pytest.fixture
def scorecard(db: _InMemoryDuckDB) -> SignalScorecard:
    return SignalScorecard(db)  # type: ignore[arg-type]


def _make_entry(
    signal_id: str = "vix_signal",
    snapshot_date: date = date(2024, 6, 1),
    is_significant: bool = True,
    is_stale: bool = False,
    horizon_days: int = 21,
) -> ScorecardEntry:
    return ScorecardEntry(
        signal_id=signal_id,
        snapshot_date=snapshot_date,
        horizon_days=horizon_days,
        ic_mean=0.12,
        ic_std=0.05,
        ic_tstat=2.8,
        ic_ir=2.4,
        hit_rate=0.55,
        sharpe_ls=0.80,
        alpha_decay_hl=45,
        is_stale=is_stale,
        staleness_days=0 if not is_stale else 7,
        is_significant=is_significant,
        weight_current=0.25,
    )


# ── Test persist + get_latest round-trip ─────────────────────────────────────

class TestScorecardPersistAndRetrieve:
    def test_persist_and_get_latest_returns_row(self, scorecard: SignalScorecard) -> None:
        entry = _make_entry()
        scorecard.persist(entry)
        df = scorecard.get_latest()
        assert not df.empty

    def test_get_latest_filters_by_signal_id(self, scorecard: SignalScorecard) -> None:
        scorecard.persist(_make_entry(signal_id="sig_a"))
        scorecard.persist(_make_entry(signal_id="sig_b"))
        df = scorecard.get_latest(signal_id="sig_a")
        assert len(df) == 1
        assert df.iloc[0]["signal_id"] == "sig_a"

    def test_persist_updates_on_conflict(self, scorecard: SignalScorecard) -> None:
        entry1 = _make_entry(signal_id="sig_x", is_significant=True)
        entry2 = ScorecardEntry(
            **{**entry1.__dict__, "is_significant": False, "ic_mean": 0.01}
        )
        scorecard.persist(entry1)
        scorecard.persist(entry2)
        df = scorecard.get_latest(signal_id="sig_x")
        # Deve avere una sola riga dopo upsert
        assert len(df) == 1
        assert df.iloc[0]["ic_mean"] == pytest.approx(0.01)

    def test_get_latest_correct_ic_mean(self, scorecard: SignalScorecard) -> None:
        entry = _make_entry()
        scorecard.persist(entry)
        df = scorecard.get_latest()
        assert df.iloc[0]["ic_mean"] == pytest.approx(0.12)

    def test_get_latest_correct_hit_rate(self, scorecard: SignalScorecard) -> None:
        entry = _make_entry()
        scorecard.persist(entry)
        df = scorecard.get_latest()
        assert df.iloc[0]["hit_rate"] == pytest.approx(0.55)

    def test_persist_from_ic_creates_entry(self, scorecard: SignalScorecard) -> None:
        ic_result = ICResult(
            signal_id="macro_signal",
            horizon_days=63,
            ic_mean=0.09,
            ic_std=0.04,
            ic_tstat=2.1,
            ic_ir=2.25,
            hit_rate=0.52,
            is_significant=True,
        )
        scorecard.persist_from_ic(
            ic_result,
            snapshot_date=date(2024, 7, 1),
            sharpe_ls=1.2,
            alpha_decay_hl=60,
        )
        df = scorecard.get_latest(signal_id="macro_signal")
        assert len(df) == 1
        assert df.iloc[0]["ic_ir"] == pytest.approx(2.25)


# ── Test get_stale_signals ────────────────────────────────────────────────────

class TestScorecardStaleSignals:
    def test_stale_signal_returned(self, scorecard: SignalScorecard) -> None:
        scorecard.persist(_make_entry(signal_id="stale_sig", is_stale=True))
        stale = scorecard.get_stale_signals()
        assert "stale_sig" in stale

    def test_fresh_signal_not_in_stale_list(self, scorecard: SignalScorecard) -> None:
        scorecard.persist(_make_entry(signal_id="fresh_sig", is_stale=False))
        stale = scorecard.get_stale_signals()
        assert "fresh_sig" not in stale

    def test_multiple_signals_correctly_filtered(self, scorecard: SignalScorecard) -> None:
        scorecard.persist(_make_entry(signal_id="stale_1", is_stale=True))
        scorecard.persist(_make_entry(signal_id="stale_2", is_stale=True))
        scorecard.persist(_make_entry(signal_id="fresh_1", is_stale=False))
        stale = scorecard.get_stale_signals()
        assert set(stale) == {"stale_1", "stale_2"}

    def test_get_active_signals_only_significant(self, scorecard: SignalScorecard) -> None:
        scorecard.persist(_make_entry(signal_id="active_sig", is_significant=True))
        scorecard.persist(_make_entry(signal_id="weak_sig", is_significant=False))
        active = scorecard.get_active_signals()
        assert "active_sig" in active
        assert "weak_sig" not in active


# ── Test get_history ─────────────────────────────────────────────────────────

class TestScorecardHistory:
    def test_get_history_returns_dataframe(self, scorecard: SignalScorecard) -> None:
        scorecard.persist(_make_entry())
        df = scorecard.get_history("vix_signal", days=90)
        assert isinstance(df, pd.DataFrame)

    def test_get_history_empty_for_unknown_signal(self, scorecard: SignalScorecard) -> None:
        df = scorecard.get_history("nonexistent_signal", days=90)
        assert df.empty
