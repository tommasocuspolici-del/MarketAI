"""Tests for shared.env_loader (v7.1.2)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from shared.env_loader import (
    ApiKeyStatus,
    EnvLoadReport,
    get_api_key_statuses,
    load_environment,
)


@pytest.fixture
def clean_env(monkeypatch):
    """Rimuove le env vars tracciate per garantire test isolati."""
    tracked = (
        "FRED_API_KEY",
        "ALPHA_VANTAGE_KEY",
        "ALPHA_VANTAGE_API_KEY",
        "FINNHUB_API_KEY",
        "ETORO_API_KEY",
        "ETORO_USER_KEY",
        "BLS_API_KEY",
        "SEC_EDGAR_USER_AGENT",
    )
    for k in tracked:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_load_environment_no_file_returns_empty_report(tmp_path, clean_env):
    """Se il file .env non esiste, ritorna report con dotenv_path=None.

    v7.1.3 (fix B5 di BUG_REPORT_v7.1.1.md): in S1 il test fallisse perche'
    ``load_environment()`` aveva un fallback su PROJECT_ROOT/.env e
    CWD/.env. Su una macchina sviluppatore con un .env reale nel progetto,
    il fallback lo trovava e ``dotenv_path`` non era None.
    Fix: isoliamo CWD su tmp_path E patchiamo PROJECT_ROOT.
    """
    # Isola CWD: il fallback CWD/.env trovera' solo file in tmp_path
    clean_env.chdir(tmp_path)
    # Isola PROJECT_ROOT del modulo env_loader: punta su una dir vuota
    clean_env.setattr(
        "shared.env_loader.PROJECT_ROOT", tmp_path, raising=True
    )

    explicit = tmp_path / "nonexistent.env"  # non lo creiamo
    report = load_environment(explicit_path=explicit)
    assert report.dotenv_path is None
    assert report.loaded_count == 0
    assert report.loaded_successfully is False


def test_load_environment_loads_file(tmp_path, clean_env):
    """Carica correttamente coppie KEY=VALUE da un file .env."""
    env_file = tmp_path / "test.env"
    env_file.write_text(
        "FRED_API_KEY=abc123\n"
        "FINNHUB_API_KEY=xyz789\n"
        "# comment\n"
        "\n"  # riga vuota
        "QUOTED='value with spaces'\n",
        encoding="utf-8",
    )
    report = load_environment(explicit_path=env_file)
    assert report.dotenv_path == env_file
    assert report.loaded_successfully is True
    assert os.environ.get("FRED_API_KEY") == "abc123"
    assert os.environ.get("FINNHUB_API_KEY") == "xyz789"
    assert os.environ.get("QUOTED") == "value with spaces"


def test_load_environment_does_not_override_existing(tmp_path, clean_env):
    """Variabili gia' in environment NON vengono sovrascritte (12-factor)."""
    clean_env.setenv("FRED_API_KEY", "preexisting")
    env_file = tmp_path / "test.env"
    env_file.write_text("FRED_API_KEY=should_not_win\n", encoding="utf-8")
    load_environment(explicit_path=env_file)
    assert os.environ.get("FRED_API_KEY") == "preexisting"


def test_get_api_key_statuses_empty_env(clean_env):
    """Senza nessuna chiave configurata, tutti gli stati sono is_set=False."""
    statuses = get_api_key_statuses()
    assert all(isinstance(s, ApiKeyStatus) for s in statuses)
    assert all(not s.is_set for s in statuses)
    assert all(not s.is_usable for s in statuses)


def test_get_api_key_statuses_detects_placeholder(clean_env):
    """I valori placeholder dal .env.example non sono 'usable'."""
    clean_env.setenv("FRED_API_KEY", "your_fred_key_here")
    statuses = get_api_key_statuses()
    fred = next(s for s in statuses if s.name == "FRED")
    assert fred.is_set is True
    assert fred.is_placeholder is True
    assert fred.is_usable is False


def test_get_api_key_statuses_detects_real_key(clean_env):
    """Una chiave reale (non placeholder, non vuota) e' usable."""
    clean_env.setenv("FRED_API_KEY", "abcdef1234567890")
    statuses = get_api_key_statuses()
    fred = next(s for s in statuses if s.name == "FRED")
    assert fred.is_set is True
    assert fred.is_placeholder is False
    assert fred.is_usable is True


def test_alpha_vantage_alias_recognized(clean_env):
    """ALPHA_VANTAGE_API_KEY e' un alias di ALPHA_VANTAGE_KEY."""
    clean_env.setenv("ALPHA_VANTAGE_API_KEY", "real_key")
    statuses = get_api_key_statuses()
    av = next(s for s in statuses if s.name == "Alpha Vantage")
    assert av.is_usable is True


def test_env_load_report_immutable():
    """EnvLoadReport e' frozen (slots=True implica anche frozen via dataclass)."""
    r = EnvLoadReport(dotenv_path=None, loaded_count=0)
    with pytest.raises((AttributeError, Exception)):
        r.loaded_count = 99  # type: ignore[misc]
