"""Tests per engine.data_universe.audit_logger — AuditLogger."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import duckdb
import pandas as pd
import pytest

from engine.data_universe.audit_logger import AuditLogger, compute_sha256


# ─── Schema SQL per in-memory DuckDB ─────────────────────────────────────────

_CREATE_TABLES = """
CREATE SEQUENCE IF NOT EXISTS seq_audit_log START 1;

CREATE TABLE IF NOT EXISTS audit_log (
    log_id           BIGINT      DEFAULT nextval('seq_audit_log'),
    event_ts         TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    operation        VARCHAR     NOT NULL,
    source           VARCHAR,
    endpoint         VARCHAR,
    data_hash_sha256 VARCHAR,
    record_count     INTEGER,
    outcome          VARCHAR,
    error_msg        VARCHAR,
    duration_ms      DOUBLE,
    PRIMARY KEY (log_id)
);
"""


# ─── Fixture ──────────────────────────────────────────────────────────────────

def _make_client() -> tuple[MagicMock, duckdb.DuckDBPyConnection]:
    conn = duckdb.connect(":memory:")
    conn.execute(_CREATE_TABLES)
    client = MagicMock()

    @contextmanager
    def _transaction():
        yield conn

    client.transaction = _transaction
    client.execute = lambda sql, params=None: conn.execute(sql, params or [])
    client.query = lambda sql, params=None: conn.execute(sql, params or []).fetchall()
    client.query_df = lambda sql, params=None: conn.execute(sql, params or []).df()
    return client, conn


@pytest.fixture()
def client_and_conn():
    return _make_client()


@pytest.fixture()
def al(client_and_conn):
    client, _ = client_and_conn
    return AuditLogger(client=client)


# ─── log_fetch ───────────────────────────────────────────────────────────────


class TestLogFetch:
    def test_log_fetch_inserts_row(
        self, al: AuditLogger, client_and_conn
    ) -> None:
        """log_fetch inserisce una riga nella tabella audit_log."""
        _, conn = client_and_conn
        al.log_fetch(source="fred", endpoint="ICSA", record_count=52, duration_ms=1430.0)
        rows = conn.execute("SELECT operation, source, endpoint, record_count, duration_ms FROM audit_log").fetchall()
        assert len(rows) == 1
        op, src, ep, cnt, dur = rows[0]
        assert op == "fetch"
        assert src == "fred"
        assert ep == "ICSA"
        assert cnt == 52
        assert dur == pytest.approx(1430.0)

    def test_log_fetch_with_error(
        self, al: AuditLogger, client_and_conn
    ) -> None:
        """log_fetch con outcome='error' salva il messaggio di errore."""
        _, conn = client_and_conn
        al.log_fetch(
            source="fred",
            endpoint="BROKEN_SERIES",
            outcome="error",
            error_msg="HTTP 503",
        )
        rows = conn.execute(
            "SELECT outcome, error_msg FROM audit_log WHERE source='fred'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "error"
        assert rows[0][1] == "HTTP 503"

    def test_log_fetch_with_data_hash(
        self, al: AuditLogger, client_and_conn
    ) -> None:
        """log_fetch salva il data_hash_sha256 se fornito."""
        _, conn = client_and_conn
        h = compute_sha256(b"payload")
        al.log_fetch(source="fred", endpoint="ICSA", data_hash=h)
        rows = conn.execute("SELECT data_hash_sha256 FROM audit_log").fetchall()
        assert rows[0][0] == h


# ─── log_write ───────────────────────────────────────────────────────────────


class TestLogWrite:
    def test_log_write_inserts_row(
        self, al: AuditLogger, client_and_conn
    ) -> None:
        """log_write inserisce una riga con operation='write'."""
        _, conn = client_and_conn
        al.log_write(
            source="vintage_manager",
            endpoint="data_vintages/ICSA",
            record_count=10,
            duration_ms=55.0,
        )
        rows = conn.execute(
            "SELECT operation, source, record_count FROM audit_log"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "write"
        assert rows[0][1] == "vintage_manager"
        assert rows[0][2] == 10

    def test_log_write_default_outcome_ok(
        self, al: AuditLogger, client_and_conn
    ) -> None:
        _, conn = client_and_conn
        al.log_write(source="lag_registry", endpoint="publication_lag_registry")
        rows = conn.execute("SELECT outcome FROM audit_log").fetchall()
        assert rows[0][0] == "ok"


# ─── log_event ───────────────────────────────────────────────────────────────


class TestLogEvent:
    def test_log_event_custom_operation(
        self, al: AuditLogger, client_and_conn
    ) -> None:
        """log_event permette operazioni personalizzate."""
        _, conn = client_and_conn
        al.log_event(
            operation="migration",
            source="migrator",
            endpoint="20260701_010_signal_quality.sql",
            record_count=0,
            duration_ms=120.0,
        )
        rows = conn.execute("SELECT operation FROM audit_log").fetchall()
        assert rows[0][0] == "migration"


# ─── get_recent ──────────────────────────────────────────────────────────────


class TestGetRecent:
    def test_get_recent_returns_dataframe(self, al: AuditLogger) -> None:
        """get_recent restituisce un DataFrame."""
        al.log_fetch(source="fred", endpoint="ICSA", record_count=5)
        df = al.get_recent(hours=1)
        assert isinstance(df, pd.DataFrame)
        assert not df.empty

    def test_get_recent_includes_all_inserted_events(
        self, al: AuditLogger
    ) -> None:
        """get_recent include tutti gli eventi inseriti."""
        al.log_fetch(source="fred", endpoint="ICSA")
        al.log_write(source="vm", endpoint="data_vintages/ICSA")
        al.log_event(operation="migration", source="sys", endpoint="sql_file")
        df = al.get_recent(hours=1)
        assert len(df) == 3

    def test_get_recent_ordered_by_event_ts_desc(self, al: AuditLogger) -> None:
        """get_recent è ordinato per event_ts decrescente."""
        al.log_fetch(source="fred", endpoint="ICSA")
        al.log_write(source="vm", endpoint="data_vintages/ICSA")
        df = al.get_recent(hours=1)
        ts_col = df["event_ts"].astype(str).tolist()
        assert ts_col == sorted(ts_col, reverse=True)

    def test_get_recent_empty_when_no_data(self, al: AuditLogger) -> None:
        """get_recent su DB vuoto restituisce DataFrame vuoto."""
        df = al.get_recent(hours=1)
        assert df.empty


# ─── get_by_source ───────────────────────────────────────────────────────────


class TestGetBySource:
    def test_filters_by_source(self, al: AuditLogger) -> None:
        """get_by_source restituisce solo eventi del source specificato."""
        al.log_fetch(source="fred", endpoint="ICSA")
        al.log_fetch(source="ecb", endpoint="/stats/exr")
        df = al.get_by_source("fred")
        assert not df.empty
        assert all(df["source"] == "fred")

    def test_unknown_source_returns_empty(self, al: AuditLogger) -> None:
        al.log_fetch(source="fred", endpoint="ICSA")
        df = al.get_by_source("nonexistent_src_xyz")
        assert df.empty


# ─── summary ─────────────────────────────────────────────────────────────────


class TestSummary:
    def test_summary_counts_by_outcome(self, al: AuditLogger) -> None:
        """summary conta gli eventi per outcome."""
        al.log_fetch(source="fred", endpoint="ICSA", outcome="ok")
        al.log_fetch(source="fred", endpoint="BAD", outcome="error", error_msg="err")
        al.log_write(source="vm", endpoint="data_vintages", outcome="ok")
        result = al.summary(hours=1)
        assert result["total"] == 3
        assert result["ok"] == 2
        assert result["error"] == 1
        assert result["partial"] == 0

    def test_summary_empty_db(self, al: AuditLogger) -> None:
        result = al.summary(hours=1)
        assert result["total"] == 0


# ─── compute_sha256 ──────────────────────────────────────────────────────────


class TestComputeSha256:
    def test_bytes_input(self) -> None:
        h = compute_sha256(b"hello world")
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex è 64 caratteri

    def test_string_input(self) -> None:
        h = compute_sha256("hello world")
        assert len(h) == 64

    def test_bytes_and_string_equivalent(self) -> None:
        assert compute_sha256("hello") == compute_sha256(b"hello")

    def test_deterministic(self) -> None:
        h1 = compute_sha256(b"payload")
        h2 = compute_sha256(b"payload")
        assert h1 == h2

    def test_different_inputs_different_hashes(self) -> None:
        assert compute_sha256(b"a") != compute_sha256(b"b")
