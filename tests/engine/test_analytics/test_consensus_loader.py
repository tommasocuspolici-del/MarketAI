"""Tests per engine.analytics.surprise_engine.consensus_loader — ConsensusLoader."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb
import pandas as pd
import pytest
import yaml

from engine.analytics.surprise_engine.consensus_loader import ConsensusBatch, ConsensusLoader


_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS consensus_estimates (
    indicator_code VARCHAR NOT NULL,
    release_date   DATE    NOT NULL,
    consensus_value DOUBLE,
    source         VARCHAR,
    loaded_at      TIMESTAMPTZ,
    PRIMARY KEY (indicator_code, release_date)
);
CREATE TABLE IF NOT EXISTS economic_consensus (
    release_date   DATE    NOT NULL,
    indicator_code VARCHAR NOT NULL,
    sector         VARCHAR,
    consensus_value DOUBLE,
    actual_value   DOUBLE,
    prior_value    DOUBLE,
    source         VARCHAR,
    PRIMARY KEY (indicator_code, release_date)
);
CREATE TABLE IF NOT EXISTS macro_series (
    series_id VARCHAR NOT NULL,
    ts        TIMESTAMPTZ NOT NULL,
    value     DOUBLE,
    PRIMARY KEY (series_id, ts)
);
"""


def _make_client():
    conn = duckdb.connect(":memory:")
    conn.execute(_CREATE_TABLES)
    client = MagicMock()

    @contextmanager
    def _transaction():
        yield conn

    client.transaction = _transaction
    client.execute = conn.execute
    client.query = lambda sql, p=None: conn.execute(sql, p or []).fetchall()
    return client, conn


def _make_loader(client=None):
    if client is None:
        client, _ = _make_client()
    with patch("engine.analytics.surprise_engine.consensus_loader.is_enabled", return_value=True):
        with patch.object(ConsensusLoader, "_load_indicator_map", return_value={}):
            return ConsensusLoader(client=client)


class TestConsensusBatch:
    def test_repr(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3]})
        batch = ConsensusBatch(df=df, source="yaml_manual", loaded_at=datetime.now(UTC))
        r = repr(batch)
        assert "yaml_manual" in r
        assert "rows=3" in r

    def test_row_count(self) -> None:
        batch = ConsensusBatch(pd.DataFrame({"x": [1]}), "test", datetime.now(UTC))
        assert batch.row_count == 1


class TestConsensusLoaderFeatureFlag:
    def test_raises_when_flag_disabled(self) -> None:
        from shared.exceptions import FeatureDisabledError
        with patch("engine.analytics.surprise_engine.consensus_loader.is_enabled", return_value=False):
            with pytest.raises(FeatureDisabledError):
                ConsensusLoader(client=MagicMock())


class TestLoadYaml:
    def test_missing_yaml_raises_config_error(self, tmp_path) -> None:
        from shared.exceptions import ConfigurationError
        loader = _make_loader()
        with pytest.raises(ConfigurationError):
            loader.load_yaml(yaml_path=tmp_path / "nonexistent.yaml")

    def test_empty_yaml_returns_empty_batch(self, tmp_path) -> None:
        yaml_file = tmp_path / "consensus.yaml"
        yaml_file.write_text("estimates: []\n", encoding="utf-8")
        loader = _make_loader()
        batch = loader.load_yaml(yaml_path=yaml_file)
        assert batch.df.empty
        assert batch.source == "yaml_manual"

    def test_valid_yaml_loaded(self, tmp_path) -> None:
        yaml_file = tmp_path / "consensus.yaml"
        yaml_file.write_text(
            "estimates:\n"
            "  - code: UNRATE\n"
            "    date: '2024-06-07'\n"
            "    consensus: 3.9\n",
            encoding="utf-8",
        )
        loader = _make_loader()
        batch = loader.load_yaml(yaml_path=yaml_file)
        assert len(batch.df) == 1
        assert batch.df.iloc[0]["indicator_code"] == "UNRATE"

    def test_skips_entries_missing_fields(self, tmp_path) -> None:
        yaml_file = tmp_path / "consensus.yaml"
        yaml_file.write_text(
            "estimates:\n"
            "  - code: UNRATE\n"
            "  - code: CPI\n"
            "    date: '2024-06-07'\n"
            "    consensus: 3.2\n",
            encoding="utf-8",
        )
        loader = _make_loader()
        batch = loader.load_yaml(yaml_path=yaml_file)
        assert len(batch.df) == 1  # UNRATE skipped (no date/consensus)

    def test_skips_non_numeric_consensus(self, tmp_path) -> None:
        yaml_file = tmp_path / "consensus.yaml"
        yaml_file.write_text(
            "estimates:\n"
            "  - code: UNRATE\n"
            "    date: '2024-06-07'\n"
            "    consensus: 'not_a_number'\n",
            encoding="utf-8",
        )
        loader = _make_loader()
        batch = loader.load_yaml(yaml_path=yaml_file)
        assert batch.df.empty

    def test_code_uppercased(self, tmp_path) -> None:
        yaml_file = tmp_path / "consensus.yaml"
        yaml_file.write_text(
            "estimates:\n"
            "  - code: unrate\n"
            "    date: '2024-06-07'\n"
            "    consensus: 3.9\n",
            encoding="utf-8",
        )
        loader = _make_loader()
        batch = loader.load_yaml(yaml_path=yaml_file)
        assert batch.df.iloc[0]["indicator_code"] == "UNRATE"


class TestLoadFredDerived:
    def test_empty_indicator_map_returns_empty(self) -> None:
        loader = _make_loader()
        batch = loader.load_fred_derived()
        assert batch.df.empty
        assert batch.source == "fred_derived"

    def test_no_fred_actual_returns_empty(self) -> None:
        client, conn = _make_client()
        with patch("engine.analytics.surprise_engine.consensus_loader.is_enabled", return_value=True):
            with patch.object(ConsensusLoader, "_load_indicator_map", return_value={
                "UNRATE": {"weight": 1.0}  # no fred_actual key
            }):
                loader = ConsensusLoader(client=client)
        batch = loader.load_fred_derived()
        assert batch.df.empty

    def test_with_macro_series_data(self) -> None:
        client, conn = _make_client()
        conn.execute(
            "INSERT INTO macro_series VALUES ('UNRATE', '2024-01-01'::TIMESTAMPTZ, 3.7)"
        )
        conn.execute(
            "INSERT INTO macro_series VALUES ('UNRATE', '2024-02-01'::TIMESTAMPTZ, 3.9)"
        )
        with patch("engine.analytics.surprise_engine.consensus_loader.is_enabled", return_value=True):
            with patch.object(ConsensusLoader, "_load_indicator_map", return_value={
                "UNRATE": {"fred_actual": "UNRATE", "sector": "labour"}
            }):
                loader = ConsensusLoader(client=client)
        batch = loader.load_fred_derived()
        assert len(batch.df) == 1
        assert batch.df.iloc[0]["indicator_code"] == "UNRATE"

    def test_db_error_returns_empty(self) -> None:
        bad_client = MagicMock()

        @contextmanager
        def _bad_tx():
            raise RuntimeError("DB fail")
            yield  # noqa

        bad_client.transaction = _bad_tx
        with patch("engine.analytics.surprise_engine.consensus_loader.is_enabled", return_value=True):
            with patch.object(ConsensusLoader, "_load_indicator_map", return_value={
                "UNRATE": {"fred_actual": "UNRATE"}
            }):
                loader = ConsensusLoader(client=bad_client)
        batch = loader.load_fred_derived()
        assert batch.df.empty


class TestSave:
    def test_empty_batch_returns_0(self) -> None:
        loader = _make_loader()
        batch = ConsensusBatch(pd.DataFrame(), "yaml_manual", datetime.now(UTC))
        assert loader.save(batch) == 0

    def test_saves_rows_to_db(self) -> None:
        client, conn = _make_client()
        loader_client = client
        with patch("engine.analytics.surprise_engine.consensus_loader.is_enabled", return_value=True):
            with patch.object(ConsensusLoader, "_load_indicator_map", return_value={}):
                loader = ConsensusLoader(client=loader_client)

        df = pd.DataFrame({
            "indicator_code": ["UNRATE"],
            "release_date": ["2024-06-07"],
            "consensus_value": [3.9],
            "source": ["yaml_manual"],
        })
        batch = ConsensusBatch(df, "yaml_manual", datetime.now(UTC))
        n = loader.save(batch)
        assert n == 1

    def test_save_db_error_raises(self) -> None:
        from shared.exceptions import DatabaseError
        bad_client = MagicMock()

        @contextmanager
        def _bad_tx():
            conn = MagicMock()
            conn.register = MagicMock()
            conn.execute = MagicMock(side_effect=RuntimeError("insert failed"))
            yield conn

        bad_client.transaction = _bad_tx
        with patch("engine.analytics.surprise_engine.consensus_loader.is_enabled", return_value=True):
            with patch.object(ConsensusLoader, "_load_indicator_map", return_value={}):
                loader = ConsensusLoader(client=bad_client)

        df = pd.DataFrame({
            "indicator_code": ["UNRATE"],
            "release_date": ["2024-06-07"],
            "consensus_value": [3.9],
        })
        batch = ConsensusBatch(df, "yaml_manual", datetime.now(UTC))
        with pytest.raises(DatabaseError):
            loader.save(batch)


class TestBuildForCalculator:
    def test_empty_db_returns_empty_df(self) -> None:
        loader = _make_loader()
        df = loader.build_for_calculator()
        assert isinstance(df, pd.DataFrame)

    def test_returns_data_when_present(self) -> None:
        client, conn = _make_client()
        conn.execute(
            "INSERT INTO economic_consensus VALUES "
            "('2024-06-07', 'UNRATE', 'labour', 3.9, 4.0, 3.8, 'fred')"
        )
        with patch("engine.analytics.surprise_engine.consensus_loader.is_enabled", return_value=True):
            with patch.object(ConsensusLoader, "_load_indicator_map", return_value={}):
                loader = ConsensusLoader(client=client)
        df = loader.build_for_calculator()
        assert len(df) == 1

    def test_db_error_returns_empty_df(self) -> None:
        bad_client = MagicMock()

        @contextmanager
        def _bad_tx():
            raise RuntimeError("query fail")
            yield  # noqa

        bad_client.transaction = _bad_tx
        with patch("engine.analytics.surprise_engine.consensus_loader.is_enabled", return_value=True):
            with patch.object(ConsensusLoader, "_load_indicator_map", return_value={}):
                loader = ConsensusLoader(client=bad_client)
        df = loader.build_for_calculator()
        assert df.empty


class TestLoadIndicatorMap:
    def test_returns_dict(self) -> None:
        result = ConsensusLoader._load_indicator_map()
        assert isinstance(result, dict)

    def test_returns_empty_on_missing_yaml(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(
            "engine.analytics.surprise_engine.consensus_loader._SURPRISE_ENGINE_YAML_PATH",
            tmp_path / "nonexistent.yaml",
        )
        result = ConsensusLoader._load_indicator_map()
        assert result == {}
