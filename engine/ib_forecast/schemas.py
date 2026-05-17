"""Schema dataclass per IB Forecast Engine (Fase 8)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

__version__ = "1.0.0"
__all__ = ["ExtractedForecast", "IBConsensus", "IBSignal"]


@dataclass
class ExtractedForecast:
    """Previsione estratta da un documento IB (regex o LLM)."""
    report_id:       str
    source:          str               # mai NULL — Regola 33
    indicator:       str               # 'GDP'|'CPI'|'FEDFUNDS'|'SP500'
    horizon:         str               # '2024'|'2025'|'Q1_2025'|'12M'
    value:           float | None = None
    value_range_low: float | None = None
    value_range_high: float | None = None
    unit:            str = "percent"
    extraction_method: str = "regex"   # 'regex'|'llm'|'api'
    confidence:      float = 0.7
    fetched_at:      datetime | None = None


@dataclass
class IBConsensus:
    """Consenso aggregato da più sorgenti IB."""
    indicator:       str
    horizon:         str
    consensus_value: float | None
    consensus_low:   float | None = None
    consensus_high:  float | None = None
    source_count:    int = 0
    sources:         list[str] = field(default_factory=list)
    method:          str = "median"
    data_quality:    str = "ok"
    computed_at:     datetime | None = None


@dataclass
class IBSignal:
    """Segnale IB per Composite Signal v3."""
    signal_date:     datetime
    score:           float           # [-1, +1]
    gdp_signal:      float | None = None
    inflation_signal: float | None = None
    rates_signal:    float | None = None
    equity_signal:   float | None = None
    source_count:    int = 0
    data_quality:    str = "ok"
