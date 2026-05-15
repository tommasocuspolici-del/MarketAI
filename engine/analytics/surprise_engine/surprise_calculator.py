"""SurpriseCalculator — calcolo z-score normalizzato per indicatore economico.

Metodologia Bloomberg/Citigroup Economic Surprise Index:
  surprise_raw = actual - consensus
  surprise_z   = surprise_raw / std_rolling(surprise_raw, window=24M)

Fonte dati: DataFrame prodotto da ConsensusLoader.build_for_calculator()
Output:     DataFrame con colonne aggiuntive surprise_raw, surprise_std, surprise_z.

Regola 8: numpy per tutti i calcoli.
Regola 12: pipeline invariabile — nessun fetch inline.
"""
from __future__ import annotations

# Re-export da surprise_engine.py (implementazione consolidata)
# Mantenuto come modulo separato per conformità alla struttura ROADMAP v4 Blocco 2.
from engine.analytics.surprise_engine.surprise_engine import (
    SurpriseCalculator,
    IndicatorSurprise,
    _NORMALIZATION_WINDOW_MONTHS,
    _SIGNIFICANCE_THRESHOLD,
)

__version__ = "1.0.0"
__all__ = [
    "SurpriseCalculator",
    "IndicatorSurprise",
]
