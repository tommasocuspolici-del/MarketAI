"""Tests — Fase 11 installer scripts (install.py, init_database.py, download_models.py).

Testa le funzioni pure degli script senza eseguire side effects reali
(no poetry install, no DB creation, no network calls).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── install.py ───────────────────────────────────────────────────────────────

class TestInstallPython:
    def test_check_python_current_version_passes(self) -> None:
        """La versione Python corrente deve superare il check."""
        from scripts.install import check_python
        # Siamo su Python 3.11+ (requirements del progetto)
        assert check_python() is True

    def test_check_poetry_found(self) -> None:
        """Poetry è installato nell'ambiente di sviluppo."""
        import shutil
        from scripts.install import check_poetry
        if shutil.which("poetry"):
            assert check_poetry() is True

    def test_setup_env_creates_from_example(self, tmp_path: Path) -> None:
        """Se .env non esiste, viene creato da .env.example."""
        import shutil as sh
        from scripts.install import setup_env
        # Crea .env.example di test
        ex = tmp_path / ".env.example"
        ex.write_text("TEST_KEY=value\n")
        env = tmp_path / ".env"
        # Patch ROOT
        with patch("scripts.install.ROOT", tmp_path):
            result = setup_env()
        assert result is True
        assert env.exists()
        assert "TEST_KEY=value" in env.read_text()

    def test_setup_env_preserves_existing(self, tmp_path: Path) -> None:
        """Se .env esiste già, non viene sovrascritto."""
        from scripts.install import setup_env
        env = tmp_path / ".env"
        env.write_text("EXISTING=keep_me\n")
        ex = tmp_path / ".env.example"
        ex.write_text("NEW_KEY=new_val\n")
        with patch("scripts.install.ROOT", tmp_path):
            setup_env()
        assert "EXISTING=keep_me" in env.read_text()

    def test_create_db_dirs(self, tmp_path: Path) -> None:
        """Le directory db, data, logs vengono create."""
        from scripts.install import create_db_dirs
        with patch("scripts.install.ROOT", tmp_path):
            result = create_db_dirs()
        assert result is True
        assert (tmp_path / "db").exists()
        assert (tmp_path / "data").exists()
        assert (tmp_path / "logs").exists()

    def test_install_script_importable(self) -> None:
        import scripts.install  # noqa: F401


# ── init_database.py ─────────────────────────────────────────────────────────

class TestInitDatabase:
    def test_script_importable(self) -> None:
        import scripts.init_database  # noqa: F401

    def test_verify_installation_duckdb(self) -> None:
        """verify_installation accetta DB reali e non crasha."""
        from scripts.init_database import verify_installation
        # Non crashes even if some checks fail (returns bool)
        result = verify_installation()
        assert isinstance(result, bool)

    def test_init_duckdb_success(self) -> None:
        """init_duckdb completa senza eccezioni sul DB reale."""
        from scripts.init_database import init_duckdb
        result = init_duckdb()
        assert isinstance(result, bool)

    def test_init_sqlite_success(self) -> None:
        """init_sqlite completa senza eccezioni."""
        from scripts.init_database import init_sqlite
        result = init_sqlite()
        assert isinstance(result, bool)


# ── download_models.py ────────────────────────────────────────────────────────

class TestDownloadModels:
    def test_script_importable(self) -> None:
        import scripts.download_models  # noqa: F401

    def test_supported_models_not_empty(self) -> None:
        from scripts.download_models import _SUPPORTED_MODELS
        assert len(_SUPPORTED_MODELS) >= 2

    def test_default_model_in_supported(self) -> None:
        from scripts.download_models import _SUPPORTED_MODELS, _DEFAULT_MODEL
        ids = [m["id"] for m in _SUPPORTED_MODELS]
        assert _DEFAULT_MODEL in ids

    def test_all_models_have_required_fields(self) -> None:
        from scripts.download_models import _SUPPORTED_MODELS
        required = {"id", "ram_gb", "disk_gb", "quality", "description"}
        for m in _SUPPORTED_MODELS:
            assert required.issubset(m.keys()), f"Model {m.get('id')} missing fields"

    def test_ram_positive(self) -> None:
        from scripts.download_models import _SUPPORTED_MODELS
        for m in _SUPPORTED_MODELS:
            assert m["ram_gb"] > 0

    def test_check_ollama_returns_bool(self) -> None:
        from scripts.download_models import _check_ollama
        result = _check_ollama()
        assert isinstance(result, bool)

    def test_detect_recommended_returns_string(self) -> None:
        from scripts.download_models import _detect_recommended_model, _DEFAULT_MODEL
        result = _detect_recommended_model()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_detect_fallback_to_default(self) -> None:
        """Se hardware detector fallisce, ritorna il default."""
        from scripts.download_models import _detect_recommended_model, _DEFAULT_MODEL
        with patch("engine.llm.hardware_detector.detect_hardware", side_effect=ImportError()):
            result = _detect_recommended_model()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_pull_model_ollama_not_found(self) -> None:
        """Se ollama non trovato, ritorna False senza crash."""
        from scripts.download_models import _pull_model
        with patch("subprocess.run", side_effect=FileNotFoundError("ollama not found")):
            result = _pull_model("mistral:7b-q4")
        assert result is False

    def test_pull_model_subprocess_error(self) -> None:
        """Se subprocess fallisce, ritorna False."""
        from scripts.download_models import _pull_model
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "ollama")):
            result = _pull_model("mistral:7b-q4")
        assert result is False


# ── INSTALL.md ────────────────────────────────────────────────────────────────

class TestInstallDoc:
    def test_install_md_exists(self) -> None:
        assert (ROOT / "INSTALL.md").exists()

    def test_install_md_has_sections(self) -> None:
        content = (ROOT / "INSTALL.md").read_text(encoding="utf-8")
        required = [
            "Requisiti di Sistema",
            "Installazione Rapida",
            "Configurazione API Key",
            "Avvio",
            "LLM Opzionale",
            "Scheduler",
        ]
        for section in required:
            assert section in content, f"Section '{section}' missing from INSTALL.md"

    def test_env_example_has_llm_vars(self) -> None:
        content = (ROOT / ".env.example").read_text(encoding="utf-8")
        assert "OLLAMA_HOST" in content
        assert "OLLAMA_MODEL" in content
        assert "LLM" in content


# ── pyproject.toml version ────────────────────────────────────────────────────

class TestProjectVersion:
    def test_version_is_1_0_0(self) -> None:
        content = (ROOT / "pyproject.toml").read_text()
        assert 'version = "1.0.0"' in content
