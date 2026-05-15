"""SectorSurpriseAggregator — indice di sorpresa settoriale con decadimento esponenziale.

Metodologia CESI (Citigroup Economic Surprise Index) adattata:
  · Media pesata z-score ultimi N mesi per settore
  · Decadimento esponenziale: λ=0.10 → half-life ~7 mesi
  · Regime: 'positive_surprise' | 'neutral' | 'negative_surprise'

Settori supportati: labour, growth, inflation, housing, trade_external.
Pesi indicatori: configurabili per settore, letti da surprise_engine.yaml.

Regola 8: numpy per calcoli.
Regola 13: persiste in sector_surprise_index DuckDB.
"""
from __future__ import annotations

# Re-export da surprise_engine.py (implementazione consolidata)
# Mantenuto come modulo separato per conformità alla struttura ROADMAP v4 Blocco 2.
from engine.analytics.surprise_engine.surprise_engine import (
    SectorSurpriseAggregator,
    SectorSurpriseIndex,
    _SECTOR_WEIGHTS,
    _AGGREGATION_MONTHS,
    _DECAY_LAMBDA,
    _REGIME_THRESHOLD,
)

__version__ = "1.0.0"
__all__ = [
    "SectorSurpriseAggregator",
    "SectorSurpriseIndex",
    "SECTOR_WEIGHTS",
]

# Alias pubblico per accesso esterno ai pesi di default
SECTOR_WEIGHTS = dict(_SECTOR_WEIGHTS)
