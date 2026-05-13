"""Pattern recognition schemas — Pydantic models and enums.

Centralizza tutti i tipi condivisi tra PatternDetector, PatternSignalsRepo
e i componenti UI. Non importa da altri sottomoduli di engine/technical/
per evitare dipendenze circolari.

Regola 9: ogni modello ha type hints completi.
Regola 8: campi numerici usano float (numpy float64 in input, float in Pydantic).
"""
from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

__version__ = "9.0.0"
__all__ = [
    "PatternDetectionConfig",
    "PatternResult",
    "PatternSignal",
    "PatternType",
    "load_pattern_config",
]

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "pattern_config.yaml"


# ─── Enumerazioni ────────────────────────────────────────────────────────────

class PatternType(StrEnum):
    """Tipo di pattern grafico riconosciuto."""
    HEAD_AND_SHOULDERS = "head_and_shoulders"
    INVERSE_HEAD_AND_SHOULDERS = "inverse_head_and_shoulders"
    DOUBLE_TOP = "double_top"
    DOUBLE_BOTTOM = "double_bottom"
    TRIANGLE_ASCENDING = "triangle_ascending"
    TRIANGLE_DESCENDING = "triangle_descending"
    TRIANGLE_SYMMETRIC = "triangle_symmetric"
    CUP_AND_HANDLE = "cup_and_handle"
    FLAG = "flag"
    PENNANT = "pennant"


class PatternSignal(StrEnum):
    """Direzione di trading implicata dal pattern."""
    BULLISH = "bullish"    # aspettativa rialzista
    BEARISH = "bearish"    # aspettativa ribassista
    NEUTRAL = "neutral"    # attesa di breakout (triangoli simmetrici)


# ─── Configurazione (caricata da pattern_config.yaml) ────────────────────────

class PatternDetectionConfig(BaseModel):
    """Parametri di rilevamento pattern, caricati da pattern_config.yaml.

    Tutti i campi hanno default robusti in caso di config mancante.
    """
    model_config = ConfigDict(frozen=True)

    pivot_order: int = Field(default=5, ge=2, le=20)
    min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)

    # H&S
    max_shoulder_asymmetry: float = Field(default=0.15)
    max_neckline_slope_ratio: float = Field(default=0.05)
    min_head_dominance: float = Field(default=0.03)

    # Double top/bottom
    max_price_proximity_pct: float = Field(default=0.03)
    min_valley_depth_pct: float = Field(default=0.02)

    # Triangle
    flat_slope_threshold: float = Field(default=0.005)
    min_slope_threshold: float = Field(default=0.003)
    triangle_window_bars: int = Field(default=60)
    min_pivot_count: int = Field(default=3)

    # Cup and handle
    min_cup_depth_pct: float = Field(default=0.10)
    max_cup_depth_pct: float = Field(default=0.50)
    max_handle_retracement_pct: float = Field(default=0.15)
    min_cup_bars: int = Field(default=20)

    # Flag / Pennant
    min_pole_move_pct: float = Field(default=0.05)
    max_consolidation_bars: int = Field(default=20)
    min_pole_bars: int = Field(default=5)


def load_pattern_config() -> PatternDetectionConfig:
    """Carica la configurazione da pattern_config.yaml.

    Fallback ai default se il file è mancante o malformato.
    """
    try:
        with _CONFIG_PATH.open() as f:
            raw: dict[str, Any] = yaml.safe_load(f) or {}
        # Flatten nested keys → flat dict per PatternDetectionConfig
        flat: dict[str, Any] = {
            "pivot_order": raw.get("pivot_order", 5),
            "min_confidence": raw.get("min_confidence", 0.6),
        }
        # H&S block
        hs = raw.get("head_and_shoulders", {})
        flat["max_shoulder_asymmetry"] = hs.get("max_shoulder_asymmetry", 0.15)
        flat["max_neckline_slope_ratio"] = hs.get("max_neckline_slope_ratio", 0.05)
        flat["min_head_dominance"] = hs.get("min_head_dominance", 0.03)
        # Double
        dt = raw.get("double_top_bottom", {})
        flat["max_price_proximity_pct"] = dt.get("max_price_proximity_pct", 0.03)
        flat["min_valley_depth_pct"] = dt.get("min_valley_depth_pct", 0.02)
        # Triangle
        tri = raw.get("triangle", {})
        flat["flat_slope_threshold"] = tri.get("flat_slope_threshold", 0.005)
        flat["min_slope_threshold"] = tri.get("min_slope_threshold", 0.003)
        flat["triangle_window_bars"] = tri.get("window_bars", 60)
        flat["min_pivot_count"] = tri.get("min_pivot_count", 3)
        # Cup
        cup = raw.get("cup_and_handle", {})
        flat["min_cup_depth_pct"] = cup.get("min_cup_depth_pct", 0.10)
        flat["max_cup_depth_pct"] = cup.get("max_cup_depth_pct", 0.50)
        flat["max_handle_retracement_pct"] = cup.get("max_handle_retracement_pct", 0.15)
        flat["min_cup_bars"] = cup.get("min_cup_bars", 20)
        # Flag
        fp = raw.get("flag_pennant", {})
        flat["min_pole_move_pct"] = fp.get("min_pole_move_pct", 0.05)
        flat["max_consolidation_bars"] = fp.get("max_consolidation_bars", 20)
        flat["min_pole_bars"] = fp.get("min_pole_bars", 5)
        return PatternDetectionConfig(**flat)
    except Exception:  # noqa: BLE001
        return PatternDetectionConfig()  # tutti i default


# ─── Risultato di rilevamento ─────────────────────────────────────────────────

class PatternResult(BaseModel):
    """Singolo pattern grafico rilevato su una serie OHLCV.

    Immutabile (frozen=True) — i risultati sono prodotti dal detector
    e non devono essere modificati a valle.
    """
    model_config = ConfigDict(frozen=True)

    ticker: str
    pattern_type: PatternType
    signal: PatternSignal
    confidence: float = Field(ge=0.0, le=1.0)

    # Posizione temporale nella serie
    start_idx: int = Field(ge=0)
    end_idx: int = Field(ge=0)
    start_date: datetime
    end_date: datetime

    # Livelli chiave (es. neckline, target, breakout_level)
    key_levels: dict[str, float] = Field(default_factory=dict)

    # Descrizione testuale leggibile
    description: str = ""

    @field_validator("end_idx")
    @classmethod
    def end_after_start(cls, v: int, info: Any) -> int:
        if "start_idx" in info.data and v < info.data["start_idx"]:
            raise ValueError("end_idx must be >= start_idx")
        return v

    @field_validator("confidence")
    @classmethod
    def round_confidence(cls, v: float) -> float:
        return round(v, 4)

    @property
    def duration_bars(self) -> int:
        """Lunghezza del pattern in barre."""
        return self.end_idx - self.start_idx

    def to_db_dict(self) -> dict[str, object]:
        """Serializzazione per PatternSignalsRepo.write()."""
        import json
        return {
            "ticker": self.ticker,
            "pattern_type": self.pattern_type.value,
            "signal_dir": self.signal.value,
            "confidence": self.confidence,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "start_idx": self.start_idx,
            "end_idx": self.end_idx,
            "key_levels_json": json.dumps(self.key_levels),
            "description": self.description[:500],
        }
