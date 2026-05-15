"""SurpriseSignalGenerator — segnale [-1, +1] per Composite Signal v2.

Converte gli indici settoriali del Surprise Engine in un segnale scalare
compatibile con CompositeSignalAggregator v2.

Pesi settoriali (configurati in surprise_engine.py):
  labour:         0.30  — leading del ciclo, alta predittività
  growth:         0.30  — coincident, impatto diretto su earnings
  inflation:      0.20  — determinante per policy Fed
  housing:        0.15  — leading ma volatile
  trade_external: 0.05  — impatto limitato su equity USA

Output signal ∈ [-1, +1]:
  +1 = tutte le sorprese fortemente positive (economia migliore del previsto)
  -1 = tutte le sorprese fortemente negative (economia peggio del previsto)

Regola 8: numpy per calcoli.
Regola 13: persiste in surprise_signal DuckDB.
"""
from __future__ import annotations

# Re-export da surprise_engine.py (implementazione consolidata)
# Mantenuto come modulo separato per conformità alla struttura ROADMAP v4 Blocco 2.
from engine.analytics.surprise_engine.surprise_engine import (
    SurpriseSignalGenerator,
    SurpriseCompositeSignal,
    _SECTOR_WEIGHTS,
)

__version__ = "1.0.0"
__all__ = [
    "SurpriseSignalGenerator",
    "SurpriseCompositeSignal",
]
