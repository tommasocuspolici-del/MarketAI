"""Pydantic / Pandera schemas per Surprise Engine (Blocco C)."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
import pandas as pd
import pandera as pa
from pandera.typing import Series

__version__ = "1.0.0"

class SurpriseOutputSchema(pa.DataFrameModel):
    release_date:   Series[pd.Timestamp]
    indicator_code: Series[str]
    sector:         Series[str]
    consensus:      Series[float] = pa.Field(nullable=True)
    actual:         Series[float] = pa.Field(nullable=True)
    surprise_raw:   Series[float] = pa.Field(nullable=True)
    surprise_std:   Series[float] = pa.Field(ge=0.0, nullable=True)
    surprise_z:     Series[float] = pa.Field(nullable=True)

    class Config:
        strict = False
        coerce = True

@dataclass(frozen=True)
class IndicatorSurprise:
    indicator_code: str
    sector:         str
    release_date:   date
    surprise_raw:   float
    surprise_z:     float
    beat:           bool
    significant:    bool
