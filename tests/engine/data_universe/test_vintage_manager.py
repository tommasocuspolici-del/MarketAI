"""Tests per engine.data_universe.vintage_manager — VintageManager."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock

import duckdb
import pandas as pd
import pytest

from engine.data_universe.vintage_manager import VintageManager, _to_date


# ─── Schema SQL per in-memory DuckDB ─────────────────────────────────────────

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS data_vintages (
    series_id          VARCHAR     NOT NULL,
    observation_date   DATE        NOT NULL,
    vintage_date       DATE        NOT NULL,
    value              DOUBLE      NOT NULL,
    is_revised         BOOLEAN     DEFAULT FALSE,
    revision_count     INTEGER     DEFAULT 0,
    first_published    DATE,
    source             VARCHAR,
    PRIMARY KEY (series_id, observation_date, vintage_date)
);
"""


# ─── Fixture: in-memory DuckDB client mock ───────────────────────────────────

def _make_client() -> tuple[MagicMock, duckdb.DuckDBPyConnection]:
    """Crea un client mock che wrappa una connessione DuckDB in-memory."""
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
def vm(client_and_conn):
    client, conn = client_and_conn
    return VintageManager(client=client)


# ─── record_vintage ───────────────────────────────────────────────────────────


class TestRecordVintage:
    def test_record_first_observation(self, vm: VintageManager) -> None:
        """La prima osservazione non è una revisione."""
        result = vm.record_vintage(
            series_id="ICSA",
            observation_date=date(2024, 1, 5),
            vintage_date=date(2024, 1, 6),
            value=215000.0,
            source="fred",
        )
        assert result == 1

    def test_record_duplicate_is_ignored(self, vm: VintageManager) -> None:
        """Inserire lo stesso (series, obs_date, vintage_date) due volte è idempotente."""
        vm.record_vintage("ICSA", date(2024, 1, 5), date(2024, 1, 6), 215000.0)
        result = vm.record_vintage("ICSA", date(2024, 1, 5), date(2024, 1, 6), 215000.0)
        # Secondo insert è ignorato (DO NOTHING)
        assert result == 1  # apply_error_policy returns 1 anche se no-op

    def test_record_revision_marks_is_revised(
        self, vm: VintageManager, client_and_conn
    ) -> None:
        """Una revisione con valore diverso viene marcata is_revised=True."""
        client, conn = client_and_conn
        vm.record_vintage("ICSA", date(2024, 1, 5), date(2024, 1, 6), 215000.0)
        vm.record_vintage("ICSA", date(2024, 1, 5), date(2024, 2, 1), 218000.0)

        rows = conn.execute(
            "SELECT is_revised, revision_count FROM data_vintages "
            "WHERE series_id='ICSA' AND vintage_date='2024-02-01'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] is True   # is_revised
        assert rows[0][1] == 1      # revision_count

    def test_record_same_value_not_revised(
        self, vm: VintageManager, client_and_conn
    ) -> None:
        """Stesso valore con vintage diverso: is_revised rimane False."""
        client, conn = client_and_conn
        vm.record_vintage("ICSA", date(2024, 1, 5), date(2024, 1, 6), 215000.0)
        vm.record_vintage("ICSA", date(2024, 1, 5), date(2024, 2, 1), 215000.0)

        rows = conn.execute(
            "SELECT is_revised FROM data_vintages "
            "WHERE series_id='ICSA' AND vintage_date='2024-02-01'"
        ).fetchall()
        assert rows[0][0] is False

    def test_record_different_series_independent(self, vm: VintageManager) -> None:
        """Due serie diverse con stessa observation_date sono indipendenti."""
        vm.record_vintage("ICSA", date(2024, 1, 5), date(2024, 1, 6), 215000.0)
        vm.record_vintage("UNRATE", date(2024, 1, 5), date(2024, 1, 6), 3.7)
        # Nessun errore — le due serie non interferiscono


# ─── bulk_record ──────────────────────────────────────────────────────────────


class TestBulkRecord:
    def test_bulk_record_inserts_all_rows(
        self, vm: VintageManager, client_and_conn
    ) -> None:
        """bulk_record inserisce tutte le righe del DataFrame."""
        client, conn = client_and_conn
        df = pd.DataFrame({
            "observation_date": [date(2024, 1, i) for i in range(1, 6)],
            "value": [210000.0 + i * 1000 for i in range(5)],
        })
        n = vm.bulk_record("ICSA", df, vintage_date=date(2024, 1, 10), source="fred")
        assert n == 5
        count = conn.execute("SELECT COUNT(*) FROM data_vintages WHERE series_id='ICSA'").fetchone()[0]
        assert count == 5

    def test_bulk_record_empty_df_returns_zero(self, vm: VintageManager) -> None:
        df = pd.DataFrame({"observation_date": [], "value": []})
        n = vm.bulk_record("ICSA", df, vintage_date=date(2024, 1, 10))
        assert n == 0


# ─── get_as_of ────────────────────────────────────────────────────────────────


class TestGetAsOf:
    def _setup_icsa(self, vm: VintageManager) -> None:
        """Popola due vintages per ICSA: uno a gennaio, uno a febbraio."""
        vm.record_vintage("ICSA", date(2024, 1, 5), date(2024, 1, 6), 215000.0)
        vm.record_vintage("ICSA", date(2024, 1, 5), date(2024, 2, 1), 218000.0)
        vm.record_vintage("ICSA", date(2024, 1, 12), date(2024, 1, 13), 220000.0)

    def test_get_as_of_before_revision(self, vm: VintageManager) -> None:
        """As-of 10 gennaio: vede solo il primo vintage."""
        self._setup_icsa(vm)
        df = vm.get_as_of("ICSA", date(2024, 1, 10))
        assert not df.empty
        # Solo obs_date 2024-01-05 con valore 215000 (vintage jan 6 ≤ jan 10)
        obs = df[df["observation_date"].astype(str) == "2024-01-05"]
        assert len(obs) == 1
        assert float(obs.iloc[0]["value"]) == pytest.approx(215000.0)

    def test_get_as_of_after_revision_picks_latest(self, vm: VintageManager) -> None:
        """As-of dopo febbraio: vede la revisione (valore 218000)."""
        self._setup_icsa(vm)
        df = vm.get_as_of("ICSA", date(2024, 3, 1))
        obs = df[df["observation_date"].astype(str) == "2024-01-05"]
        assert len(obs) == 1
        assert float(obs.iloc[0]["value"]) == pytest.approx(218000.0)

    def test_get_as_of_empty_for_unknown_series(self, vm: VintageManager) -> None:
        df = vm.get_as_of("NONEXISTENT_XYZ", date(2024, 1, 1))
        assert df.empty

    def test_get_as_of_ordered_by_observation_date(self, vm: VintageManager) -> None:
        """Il risultato è ordinato per observation_date crescente."""
        self._setup_icsa(vm)
        df = vm.get_as_of("ICSA", date(2024, 3, 1))
        dates = list(df["observation_date"].astype(str))
        assert dates == sorted(dates)


# ─── detect_revisions ────────────────────────────────────────────────────────


class TestDetectRevisions:
    def test_detects_revision_with_abs_and_pct(
        self, vm: VintageManager, client_and_conn
    ) -> None:
        """detect_revisions calcola revision_abs e revision_pct."""
        client, conn = client_and_conn
        # Inserisci manualmente con is_revised=True
        conn.execute(
            "INSERT INTO data_vintages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ["ICSA", date(2024, 1, 5), date(2024, 1, 6), 215000.0, False, 0, date(2024, 1, 6), "fred"],
        )
        conn.execute(
            "INSERT INTO data_vintages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ["ICSA", date(2024, 1, 5), date(2024, 2, 1), 218000.0, True, 1, date(2024, 1, 6), "fred"],
        )
        df = vm.detect_revisions("ICSA")
        assert not df.empty
        row = df.iloc[0]
        assert float(row["revision_abs"]) == pytest.approx(3000.0)
        pct = float(row["revision_pct"])
        assert pytest.approx(pct, rel=0.01) == 3000.0 / 215000.0 * 100.0

    def test_no_revisions_returns_empty(self, vm: VintageManager) -> None:
        """Senza revisioni, detect_revisions restituisce DataFrame vuoto."""
        vm.record_vintage("ICSA", date(2024, 1, 5), date(2024, 1, 6), 215000.0)
        df = vm.detect_revisions("ICSA")
        assert df.empty


# ─── get_revision_stats ───────────────────────────────────────────────────────


class TestGetRevisionStats:
    def test_stats_with_no_data_returns_zeros(self, vm: VintageManager) -> None:
        stats = vm.get_revision_stats("NONEXISTENT")
        assert stats["total_revisions"] == 0
        assert stats["avg_revision_abs"] == 0.0
        assert stats["series_id"] == "NONEXISTENT"

    def test_stats_includes_series_id(self, vm: VintageManager) -> None:
        stats = vm.get_revision_stats("ICSA")
        assert stats["series_id"] == "ICSA"


# ─── _to_date utility ────────────────────────────────────────────────────────


class TestToDate:
    def test_date_passthrough(self) -> None:
        d = date(2024, 1, 5)
        assert _to_date(d) == d

    def test_datetime_to_date(self) -> None:
        from datetime import datetime, timezone
        dt = datetime(2024, 1, 5, 12, 0, tzinfo=timezone.utc)
        assert _to_date(dt) == date(2024, 1, 5)

    def test_string_iso_format(self) -> None:
        assert _to_date("2024-01-05") == date(2024, 1, 5)

    def test_pandas_timestamp(self) -> None:
        ts = pd.Timestamp("2024-01-05")
        assert _to_date(ts) == date(2024, 1, 5)

    def test_invalid_string_returns_none(self) -> None:
        assert _to_date("not-a-date") is None

    def test_none_returns_none(self) -> None:
        assert _to_date(None) is None
