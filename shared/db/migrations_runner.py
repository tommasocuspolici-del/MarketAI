"""Auto-migrations runner per SQLite all'avvio dell'app (v7.1.3).

Risolve B3 di BUG_REPORT_v7.1.1.md: il database SQLite veniva creato
vuoto (nessuna tabella) se l'utente non ricordava di lanciare
``alembic upgrade head`` manualmente, causando crash come
``no such table: cash_flow_entries``.

Funzionamento:

  - Alembic viene chiamato programmaticamente con ``command.upgrade()``.
  - L'operazione e' idempotente: se le migration sono gia' tutte applicate,
    Alembic non fa nulla.
  - Errori vengono catturati e loggati: la UI partira' comunque (con DB
    eventualmente vuoto), ma l'utente vede un warning.
  - Diagnostica: la funzione ritorna ``MigrationsReport`` per uso UI.

Convenzioni v6.0 rispettate: type hints completi, structlog, no print,
nessuna magia (alembic.ini path esplicito da PROJECT_ROOT).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from shared.constants import PROJECT_ROOT
from shared.logger import get_logger

__version__ = "7.1.3"

__all__ = [
    "MigrationsReport",
    "apply_sqlite_migrations",
]

log = get_logger(__name__)

# Percorso canonico di alembic.ini — relativo a PROJECT_ROOT.
_DEFAULT_ALEMBIC_INI: Path = PROJECT_ROOT / "alembic.ini"

# Env var per disattivare le auto-migrations (utile in test/CI dove le
# fixtures potrebbero gestirle diversamente).
_DISABLE_ENV_VAR = "MARKETAI_DISABLE_AUTO_MIGRATIONS"


@dataclass(frozen=True, slots=True)
class MigrationsReport:
    """Esito dell'applicazione delle migration."""

    applied: bool
    error: str | None = None
    alembic_ini_path: Path | None = None
    skipped_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        """True se le migration sono state applicate (o erano gia' aggiornate)."""
        return self.applied and self.error is None


def apply_sqlite_migrations(
    alembic_ini_path: Path | None = None,
) -> MigrationsReport:
    """Applica le migration SQLite Alembic in modo idempotente.

    Usata in ``app_unified.py`` all'avvio per garantire che il DB abbia
    sempre le tabelle attese. Idempotente: se le migration sono gia'
    a "head", Alembic non fa side-effect.

    Args:
        alembic_ini_path: Percorso esplicito di alembic.ini. Default
            ``PROJECT_ROOT/alembic.ini``.

    Returns:
        :class:`MigrationsReport` con esito + eventuale errore. NON solleva
        eccezioni: il caller decide se mostrare il warning o procedere.
    """
    # Bypass esplicito (per test/CI dove le fixture gestiscono separatamente)
    if os.environ.get(_DISABLE_ENV_VAR, "").strip().lower() in ("1", "true", "yes"):
        return MigrationsReport(
            applied=False,
            skipped_reason=f"Disattivato via env var {_DISABLE_ENV_VAR}",
        )

    ini_path = alembic_ini_path or _DEFAULT_ALEMBIC_INI
    if not ini_path.is_file():
        return MigrationsReport(
            applied=False,
            error=f"alembic.ini non trovato: {ini_path}",
            alembic_ini_path=ini_path,
        )

    try:
        # Import locale: alembic e' una dipendenza pesante e l'app deve
        # poter partire (con avviso) anche senza
        from alembic import command
        from alembic.config import Config
    except ImportError as exc:
        return MigrationsReport(
            applied=False,
            error=(
                f"alembic non installato: {exc}. "
                "Installa con: poetry install"
            ),
            alembic_ini_path=ini_path,
        )

    try:
        cfg = Config(str(ini_path))
        # Deve essere relativo a project root (alembic.ini ha
        # script_location=shared/db/migrations/sqlite). Setto explicit.
        cfg.set_main_option(
            "script_location",
            str(PROJECT_ROOT / "shared" / "db" / "migrations" / "sqlite"),
        )
        command.upgrade(cfg, "head")
    except Exception as exc:  # noqa: BLE001 -- vogliamo catturare ogni errore alembic
        log.error(
            "auto_migrations.failed",
            error=str(exc),
            alembic_ini=str(ini_path),
        )
        return MigrationsReport(
            applied=False,
            error=str(exc),
            alembic_ini_path=ini_path,
        )

    log.info(
        "auto_migrations.applied",
        alembic_ini=str(ini_path),
    )
    return MigrationsReport(
        applied=True,
        alembic_ini_path=ini_path,
    )
