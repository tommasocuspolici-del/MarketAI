"""Utility condivise tra i moduli job dello scheduler MarketAI.

Estratto da run_scheduler.py (era 830 righe, violava Regola 2).

Contiene: _PROJECT_ROOT, _run_async, setup sys.path.
Importato da scheduler_jobs_data.py e scheduler_jobs_analysis.py.

ANTI-REGRESSIONE: la manipolazione sys.path deve avvenire
PRIMA di qualsiasi import dai moduli dell'app. I job file devono
importare scheduler_utils come PRIMO import non-stdlib.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# ROOT del progetto — 2 livelli sopra scripts/
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Assicura che il root sia nel path PRIMA di qualsiasi import app
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Ora è sicuro importare dai moduli dell'app
from shared.error_budget import error_budget  # noqa: E402
from shared.logger import get_logger         # noqa: E402

log = get_logger("scheduler")

__all__ = ["_PROJECT_ROOT", "_run_async", "error_budget", "log"]


def _run_async(coro) -> object:  # type: ignore[no-untyped-def]
    """Esegui una coroutine da un contesto sincrono (APScheduler).

    ANTI-REGRESSIONE: APScheduler chiama i job in thread sincroni.
    asyncio.run() fallisce se c'è già un loop attivo (es. Jupyter/test).
    Il fallback new_event_loop() copre questo caso.
    """
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
