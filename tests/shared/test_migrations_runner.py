"""Tests per shared.db.migrations_runner v7.1.3 (B3).

Verifica che apply_sqlite_migrations() ritorni report sensato senza
sollevare eccezioni in nessun caso.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from shared.db.migrations_runner import (
    MigrationsReport,
    apply_sqlite_migrations,
)


def test_report_when_alembic_ini_missing(tmp_path):
    """Se alembic.ini non esiste, ritorna report con error, non solleva."""
    fake = tmp_path / "nonexistent_alembic.ini"
    report = apply_sqlite_migrations(alembic_ini_path=fake)
    assert isinstance(report, MigrationsReport)
    assert report.applied is False
    assert report.error is not None
    assert "alembic.ini" in report.error.lower()
    assert report.succeeded is False


def test_report_disabled_via_env_var(tmp_path, monkeypatch):
    """L'env var MARKETAI_DISABLE_AUTO_MIGRATIONS=1 disabilita il runner."""
    monkeypatch.setenv("MARKETAI_DISABLE_AUTO_MIGRATIONS", "1")
    # Anche con alembic.ini valido (qui non lo creiamo, ma e' irrilevante:
    # il check disabled avviene PRIMA del check del file)
    fake = tmp_path / "alembic.ini"
    fake.write_text("[alembic]\nscript_location = .")
    report = apply_sqlite_migrations(alembic_ini_path=fake)
    assert report.applied is False
    assert report.error is None
    assert report.skipped_reason is not None
    assert "MARKETAI_DISABLE_AUTO_MIGRATIONS" in report.skipped_reason


@pytest.mark.parametrize("value", ["1", "true", "yes", "True", "YES"])
def test_disable_env_var_case_insensitive(value, tmp_path, monkeypatch):
    """L'env var accetta variazioni di case e valori comuni."""
    monkeypatch.setenv("MARKETAI_DISABLE_AUTO_MIGRATIONS", value)
    fake = tmp_path / "alembic.ini"
    fake.write_text("[alembic]\nscript_location = .")
    report = apply_sqlite_migrations(alembic_ini_path=fake)
    assert report.applied is False
    assert report.skipped_reason is not None


def test_disable_env_var_other_values_dont_disable(tmp_path, monkeypatch):
    """Valori non riconosciuti (e.g. '0', 'no') NON disabilitano il runner."""
    monkeypatch.setenv("MARKETAI_DISABLE_AUTO_MIGRATIONS", "0")
    # Con questo file non valido fallira', ma NON sara' "skipped"
    fake = tmp_path / "missing_alembic.ini"
    report = apply_sqlite_migrations(alembic_ini_path=fake)
    assert report.skipped_reason is None  # non e' stato skippato
    assert report.error is not None  # e' fallito (path non esiste)


def test_migrations_report_immutable():
    """MigrationsReport e' frozen."""
    r = MigrationsReport(applied=True)
    with pytest.raises((AttributeError, Exception)):
        r.applied = False  # type: ignore[misc]


def test_migrations_report_succeeded_property():
    """succeeded = applied AND no error."""
    assert MigrationsReport(applied=True).succeeded is True
    assert MigrationsReport(applied=False).succeeded is False
    assert MigrationsReport(applied=True, error="boom").succeeded is False
