#!/usr/bin/env python3
"""Manual backup runner.

Usage:
    python scripts/backup.py
    make backup

Exit codes:
    0 — success
    1 — backup failure
"""
from __future__ import annotations

import sys
from pathlib import Path

# Inserisce la root del progetto in sys.path quando lanciato da CLI
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared.backup_manager import BackupManager  # noqa: E402
from shared.exceptions import BackupError  # noqa: E402
from shared.logger import configure_logging, get_logger  # noqa: E402


def main() -> int:
    configure_logging()
    log = get_logger("backup_script")

    try:
        mgr = BackupManager()
        archive = mgr.run_backup()
        log.info("backup.script_done", path=str(archive))
        print(f"✓ Backup completed: {archive}")
        return 0
    except BackupError as exc:
        log.error("backup.script_failed", error=str(exc))
        print(f"✗ Backup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
