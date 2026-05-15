"""Tests for shared.env_loader (v7.1.2)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from shared.env_loader import (
    ApiKeyStatus,
    EnvLoadReport,
    _candidate_paths,
    _is_placeholder,
    _load_dotenv_file,
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


# ─── Tests for private helpers (uncovered lines) ──────────────────────────────

class TestIsPlaceholder:
    def test_your_prefix_caught(self) -> None:
        assert _is_placeholder("your_api_key_here") is True

    def test_YOUR_prefix_caught(self) -> None:
        assert _is_placeholder("YOUR_FRED_KEY") is True

    def test_angle_bracket_prefix(self) -> None:
        assert _is_placeholder("<YOUR_KEY_HERE>") is True

    def test_real_value_passes(self) -> None:
        assert _is_placeholder("real_secret_value_xyz") is False

    def test_known_placeholder_set_value(self) -> None:
        assert _is_placeholder("xxx") is True
        assert _is_placeholder("TODO") is True
        assert _is_placeholder("changeme") is True

    def test_empty_is_placeholder(self) -> None:
        assert _is_placeholder("") is True

    def test_whitespace_stripped_before_check(self) -> None:
        assert _is_placeholder("  your_key  ") is True


class TestLoadDotenvFile:
    def test_loads_key_value(self, tmp_path, monkeypatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("DOTENV_TEST_A=valueA\n", encoding="utf-8")
        monkeypatch.delenv("DOTENV_TEST_A", raising=False)
        n = _load_dotenv_file(env_file)
        assert n == 1
        assert os.environ.get("DOTENV_TEST_A") == "valueA"

    def test_skips_existing_env_var(self, tmp_path, monkeypatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("DOTENV_EXISTING=new\n", encoding="utf-8")
        monkeypatch.setenv("DOTENV_EXISTING", "original")
        n = _load_dotenv_file(env_file)
        assert n == 0
        assert os.environ["DOTENV_EXISTING"] == "original"

    def test_skips_comment_lines(self, tmp_path, monkeypatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\nDOTENV_AFTER_COMMENT=ok\n", encoding="utf-8")
        monkeypatch.delenv("DOTENV_AFTER_COMMENT", raising=False)
        _load_dotenv_file(env_file)
        assert os.environ.get("DOTENV_AFTER_COMMENT") == "ok"

    def test_skips_blank_lines(self, tmp_path, monkeypatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("\n\nDOTENV_BLANK=yes\n\n", encoding="utf-8")
        monkeypatch.delenv("DOTENV_BLANK", raising=False)
        _load_dotenv_file(env_file)
        assert os.environ.get("DOTENV_BLANK") == "yes"

    def test_strips_double_quotes(self, tmp_path, monkeypatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text('DOTENV_DQ="quoted"\n', encoding="utf-8")
        monkeypatch.delenv("DOTENV_DQ", raising=False)
        _load_dotenv_file(env_file)
        assert os.environ.get("DOTENV_DQ") == "quoted"

    def test_strips_single_quotes(self, tmp_path, monkeypatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("DOTENV_SQ='single'\n", encoding="utf-8")
        monkeypatch.delenv("DOTENV_SQ", raising=False)
        _load_dotenv_file(env_file)
        assert os.environ.get("DOTENV_SQ") == "single"

    def test_export_prefix_stripped(self, tmp_path, monkeypatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("export DOTENV_EXPORT=exported\n", encoding="utf-8")
        monkeypatch.delenv("DOTENV_EXPORT", raising=False)
        _load_dotenv_file(env_file)
        assert os.environ.get("DOTENV_EXPORT") == "exported"

    def test_inline_comment_stripped(self, tmp_path, monkeypatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("DOTENV_INLINE=val # comment\n", encoding="utf-8")
        monkeypatch.delenv("DOTENV_INLINE", raising=False)
        _load_dotenv_file(env_file)
        assert os.environ.get("DOTENV_INLINE") == "val"

    def test_returns_0_for_missing_file(self, tmp_path) -> None:
        n = _load_dotenv_file(tmp_path / "missing.env")
        assert n == 0

    def test_skips_line_without_equals(self, tmp_path, monkeypatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("NO_EQUALS\nWITH_EQUALS=yes\n", encoding="utf-8")
        monkeypatch.delenv("NO_EQUALS", raising=False)
        monkeypatch.delenv("WITH_EQUALS", raising=False)
        n = _load_dotenv_file(env_file)
        assert n == 1


class TestCandidatePaths:
    def test_explicit_path_first(self, tmp_path) -> None:
        explicit = tmp_path / "explicit.env"
        paths = _candidate_paths(explicit)
        assert paths[0] == explicit

    def test_none_explicit_excludes_none(self, tmp_path) -> None:
        paths = _candidate_paths(None)
        assert None not in paths
        assert len(paths) >= 1

    def test_no_duplicates_when_cwd_matches_project(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("shared.env_loader.PROJECT_ROOT", tmp_path)
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            paths = _candidate_paths(None)
            # Check no duplicate paths
            assert len(paths) == len(set(paths))
        finally:
            os.chdir(original_cwd)


class TestLoadEnvironmentFallback:
    def test_stdlib_fallback_when_dotenv_missing(self, tmp_path, monkeypatch) -> None:
        """_load_dotenv_file used as fallback when python-dotenv unavailable."""
        env_file = tmp_path / ".env"
        env_file.write_text("STDLIB_TEST_KEY=from_stdlib\n", encoding="utf-8")
        monkeypatch.delenv("STDLIB_TEST_KEY", raising=False)

        import builtins
        real_import = builtins.__import__

        def _block_dotenv(name, *args, **kwargs):
            if name == "dotenv":
                raise ImportError("blocked for test")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _block_dotenv)
        report = load_environment(explicit_path=env_file)
        assert report.dotenv_path == env_file
        assert report.loaded_successfully is True
