"""Tests for S2_Settings data loaders — no Streamlit dependency."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from presentation.dashboard_engine.pages.S2_Settings import (
    _create_backup,
    _list_backups,
    _load_db_sizes,
    _load_feature_flags,
    _load_retention_config,
    _save_feature_flags,
)


class TestLoadFeatureFlags:
    def test_returns_dict(self) -> None:
        result = _load_feature_flags()
        assert isinstance(result, dict)

    def test_all_values_are_bool(self) -> None:
        flags = _load_feature_flags()
        for k, v in flags.items():
            assert isinstance(v, bool), f"Flag {k!r} value {v!r} is not bool"

    def test_known_flags_present(self) -> None:
        flags = _load_feature_flags()
        assert "health_monitoring" in flags
        assert "auto_backup_daily" in flags

    def test_returns_copy(self) -> None:
        f1 = _load_feature_flags()
        f2 = _load_feature_flags()
        assert f1 is not f2   # defensive copy


class TestLoadRetentionConfig:
    def test_returns_dict(self) -> None:
        result = _load_retention_config()
        assert isinstance(result, dict)

    def test_has_duckdb_section(self) -> None:
        config = _load_retention_config()
        assert "duckdb" in config

    def test_has_sqlite_section(self) -> None:
        config = _load_retention_config()
        assert "sqlite" in config

    def test_retention_values_are_ints(self) -> None:
        config = _load_retention_config()
        for section in ["duckdb", "sqlite"]:
            for k, v in config.get(section, {}).items():
                if isinstance(v, int):
                    assert v >= 1, f"Retention for {section}.{k} must be ≥ 1 year"

    def test_missing_file_returns_empty(self) -> None:
        with patch(
            "presentation.dashboard_engine.pages.S2_Settings._retention_path",
            return_value=Path("/nonexistent/path.yaml"),
        ):
            result = _load_retention_config()
        assert result == {}


class TestLoadDbSizes:
    def test_returns_dict(self) -> None:
        result = _load_db_sizes()
        assert isinstance(result, dict)

    def test_has_duckdb_key(self) -> None:
        result = _load_db_sizes()
        assert any("DuckDB" in k for k in result)

    def test_has_sqlite_key(self) -> None:
        result = _load_db_sizes()
        assert any("SQLite" in k for k in result)

    def test_sizes_are_floats(self) -> None:
        result = _load_db_sizes()
        for k, v in result.items():
            assert isinstance(v, float), f"Size for {k!r} is not float"
            assert v >= 0.0


class TestListBackups:
    def test_returns_list(self) -> None:
        result = _list_backups()
        assert isinstance(result, list)

    def test_each_entry_has_required_keys(self) -> None:
        result = _list_backups()
        for entry in result:
            assert "file" in entry
            assert "path" in entry
            assert "size_mb" in entry
            assert "created" in entry

    def test_sorted_newest_first(self) -> None:
        result = _list_backups()
        if len(result) >= 2:
            assert result[0]["created"] >= result[1]["created"]


class TestCreateBackup:
    def test_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch(
                "presentation.dashboard_engine.pages.S2_Settings._backup_dir",
                return_value=tmp_path,
            ):
                dest = _create_backup()
            assert dest.exists()
            assert dest.suffix == ".duckdb"

    def test_filename_has_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch(
                "presentation.dashboard_engine.pages.S2_Settings._backup_dir",
                return_value=tmp_path,
            ):
                dest = _create_backup()
            assert "market_data_" in dest.name


class TestSaveFeatureFlags:
    def test_persists_to_yaml(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            yaml.safe_dump({"test_flag": False, "other_flag": True}, f)
            tmp_path = Path(f.name)

        try:
            with patch(
                "presentation.dashboard_engine.pages.S2_Settings._flags_path",
                return_value=tmp_path,
            ):
                with patch("shared.feature_flags.reload_flags"):
                    _save_feature_flags({"test_flag": True})

            loaded = yaml.safe_load(tmp_path.read_text())
            assert loaded["test_flag"] is True
            assert loaded["other_flag"] is True  # unchanged
        finally:
            tmp_path.unlink(missing_ok=True)
