"""Tests per engine.technical.pattern_signals_repo — PatternSignalsRepo."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import duckdb
import pytest

from engine.technical.pattern_schemas import PatternResult, PatternSignal, PatternType
from engine.technical.pattern_signals_repo import (
    PatternSignalsRepo,
    get_pattern_signals_repo,
    reset_pattern_signals_repo,
)


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS pattern_signals (
    signal_id      VARCHAR        NOT NULL DEFAULT gen_random_uuid()::VARCHAR,
    ticker         VARCHAR        NOT NULL,
    pattern_type   VARCHAR        NOT NULL,
    signal_dir     VARCHAR        NOT NULL,
    confidence     DOUBLE         NOT NULL,
    start_date     TIMESTAMPTZ    NOT NULL,
    end_date       TIMESTAMPTZ    NOT NULL,
    start_idx      INTEGER        NOT NULL,
    end_idx        INTEGER        NOT NULL,
    key_levels_json VARCHAR,
    description    VARCHAR,
    detected_at    TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    status         VARCHAR        NOT NULL DEFAULT 'ACTIVE',
    PRIMARY KEY (signal_id)
)
"""


def _make_client():
    conn = duckdb.connect(":memory:")
    conn.execute(_CREATE_TABLE)
    client = MagicMock()

    @contextmanager
    def _transaction():
        yield conn

    client.transaction = _transaction
    return client


def _make_result(
    ticker: str = "AAPL",
    pattern_type: PatternType = PatternType.DOUBLE_BOTTOM,
    signal: PatternSignal = PatternSignal.BULLISH,
    confidence: float = 0.75,
    start_idx: int = 0,
    end_idx: int = 10,
) -> PatternResult:
    now = datetime.now(UTC)
    return PatternResult(
        ticker=ticker,
        pattern_type=pattern_type,
        signal=signal,
        confidence=confidence,
        start_idx=start_idx,
        end_idx=end_idx,
        start_date=now - timedelta(days=10),
        end_date=now,
        key_levels={"target": 150.0},
        description="Test pattern",
    )


@pytest.fixture
def client():
    return _make_client()


@pytest.fixture
def repo(client):
    return PatternSignalsRepo(client=client)


class TestWrite:
    def test_write_empty_returns_0(self, repo) -> None:
        assert repo.write([]) == 0

    def test_write_single_returns_1(self, repo) -> None:
        n = repo.write([_make_result()])
        assert n == 1

    def test_write_multiple(self, repo) -> None:
        results = [_make_result("AAPL"), _make_result("MSFT")]
        n = repo.write(results)
        assert n == 2

    def test_written_data_readable(self, repo) -> None:
        repo.write([_make_result("AAPL")])
        df = repo.read_latest("AAPL", n=5)
        assert len(df) == 1
        assert df.iloc[0]["ticker"] == "AAPL"

    def test_write_raises_on_db_error(self) -> None:
        from shared.exceptions import DatabaseError
        bad_client = MagicMock()

        @contextmanager
        def _bad_tx():
            raise RuntimeError("DB error")
            yield  # noqa: unreachable

        bad_client.transaction = _bad_tx
        repo = PatternSignalsRepo(client=bad_client)
        with pytest.raises(DatabaseError):
            repo.write([_make_result()])


class TestReadLatest:
    def test_read_latest_empty_returns_empty_df(self, repo) -> None:
        df = repo.read_latest("AAPL")
        assert df.empty

    def test_read_latest_n_limit(self, repo) -> None:
        for _ in range(5):
            repo.write([_make_result("AAPL")])
        df = repo.read_latest("AAPL", n=3)
        assert len(df) == 3

    def test_read_latest_filters_by_ticker(self, repo) -> None:
        repo.write([_make_result("AAPL"), _make_result("MSFT")])
        df = repo.read_latest("AAPL")
        assert all(df["ticker"] == "AAPL")

    def test_read_latest_error_returns_empty_df(self) -> None:
        bad_client = MagicMock()

        @contextmanager
        def _bad_tx():
            raise RuntimeError("query fail")
            yield  # noqa: unreachable

        bad_client.transaction = _bad_tx
        repo = PatternSignalsRepo(client=bad_client)
        df = repo.read_latest("AAPL")
        assert df.empty


class TestReadByType:
    def test_read_by_type_returns_matching(self, repo) -> None:
        repo.write([
            _make_result("AAPL", pattern_type=PatternType.DOUBLE_BOTTOM),
            _make_result("MSFT", pattern_type=PatternType.DOUBLE_TOP),
        ])
        df = repo.read_by_type(PatternType.DOUBLE_BOTTOM)
        assert len(df) == 1
        assert df.iloc[0]["pattern_type"] == "double_bottom"

    def test_read_by_type_string_input(self, repo) -> None:
        repo.write([_make_result("AAPL", pattern_type=PatternType.DOUBLE_BOTTOM)])
        df = repo.read_by_type("double_bottom")
        assert len(df) == 1

    def test_read_by_type_empty_returns_empty(self, repo) -> None:
        df = repo.read_by_type(PatternType.HEAD_AND_SHOULDERS)
        assert df.empty

    def test_read_by_type_error_returns_empty(self) -> None:
        bad_client = MagicMock()

        @contextmanager
        def _bad_tx():
            raise RuntimeError("fail")
            yield  # noqa: unreachable

        bad_client.transaction = _bad_tx
        repo = PatternSignalsRepo(client=bad_client)
        df = repo.read_by_type(PatternType.DOUBLE_BOTTOM)
        assert df.empty


class TestReadActive:
    def test_read_active_returns_list(self, repo) -> None:
        repo.write([_make_result("AAPL")])
        results = repo.read_active("AAPL")
        assert isinstance(results, list)
        assert len(results) == 1

    def test_read_active_dict_fields(self, repo) -> None:
        repo.write([_make_result("AAPL", confidence=0.8)])
        results = repo.read_active("AAPL")
        r = results[0]
        assert "pattern_type" in r
        assert "signal_dir" in r
        assert "confidence" in r
        assert "key_levels" in r
        assert r["confidence"] == pytest.approx(0.8)

    def test_read_active_empty_ticker_returns_empty(self, repo) -> None:
        results = repo.read_active("UNKNOWN")
        assert results == []

    def test_read_active_key_levels_json_parsed(self, repo) -> None:
        repo.write([_make_result("AAPL")])
        results = repo.read_active("AAPL")
        assert isinstance(results[0]["key_levels"], dict)

    def test_read_active_error_returns_empty(self) -> None:
        bad_client = MagicMock()

        @contextmanager
        def _bad_tx():
            raise RuntimeError("fail")
            yield  # noqa: unreachable

        bad_client.transaction = _bad_tx
        repo = PatternSignalsRepo(client=bad_client)
        results = repo.read_active("AAPL")
        assert results == []


class TestCountByTicker:
    def test_count_zero_for_unknown_ticker(self, repo) -> None:
        assert repo.count_by_ticker("UNKNOWN") == 0

    def test_count_after_write(self, repo) -> None:
        repo.write([_make_result("AAPL"), _make_result("AAPL")])
        assert repo.count_by_ticker("AAPL") == 2

    def test_count_filters_by_ticker(self, repo) -> None:
        repo.write([_make_result("AAPL"), _make_result("MSFT")])
        assert repo.count_by_ticker("AAPL") == 1
        assert repo.count_by_ticker("MSFT") == 1


class TestExpireOld:
    def test_expire_returns_int(self, repo) -> None:
        repo.write([_make_result("AAPL")])
        n = repo.expire_old(days=0)
        assert isinstance(n, int)

    def test_expire_0_days_does_not_expire_fresh_records(self, repo) -> None:
        # Records inserted NOW are after today's midnight cutoff → not expired
        repo.write([_make_result("AAPL")])
        n = repo.expire_old(days=0)
        assert n == 0  # fresh records are NOT before today_midnight

    def test_expire_future_days_marks_none(self, repo) -> None:
        repo.write([_make_result("AAPL")])
        n = repo.expire_old(days=9999)
        assert n == 0

    def test_expire_on_error_returns_0(self) -> None:
        bad_client = MagicMock()

        @contextmanager
        def _bad_tx():
            raise RuntimeError("fail")
            yield  # noqa: unreachable

        bad_client.transaction = _bad_tx
        repo = PatternSignalsRepo(client=bad_client)
        assert repo.expire_old() == 0


class TestSingleton:
    def setup_method(self):
        reset_pattern_signals_repo()

    def teardown_method(self):
        reset_pattern_signals_repo()

    def test_get_returns_instance(self) -> None:
        from unittest.mock import patch
        with patch("engine.technical.pattern_signals_repo.get_duckdb_client") as mock_client:
            mock_client.return_value = _make_client()
            repo = get_pattern_signals_repo()
            assert isinstance(repo, PatternSignalsRepo)

    def test_get_same_instance(self) -> None:
        with patch("engine.technical.pattern_signals_repo.get_duckdb_client") as mock_client:
            mock_client.return_value = _make_client()
            r1 = get_pattern_signals_repo()
            r2 = get_pattern_signals_repo()
            assert r1 is r2

    def test_reset_clears_singleton(self) -> None:
        with patch("engine.technical.pattern_signals_repo.get_duckdb_client") as mock_client:
            mock_client.return_value = _make_client()
            r1 = get_pattern_signals_repo()
            reset_pattern_signals_repo()
            r2 = get_pattern_signals_repo()
            assert r1 is not r2


from unittest.mock import patch
