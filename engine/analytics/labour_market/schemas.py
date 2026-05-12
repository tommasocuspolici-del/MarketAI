"""Pydantic / Pandera schemas per Labour Market (Blocco B).

Regola 9: ogni DataFrame ha schema Pandera esplicito.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Literal

import pandas as pd
import pandera as pa
from pandera.typing import DataFrame, Series

__version__ = "1.0.0"
__all__ = [
    "JOLTSOutputSchema", "ClaimsOutputSchema",
    "PayrollOutputSchema", "LabourForecastResult",
    "ForecastBundle",
]

LabourRegime = Literal["tight", "balanced", "slack", "deteriorating"]
Horizon = Literal["1M", "3M", "6M"]


class JOLTSOutputSchema(pa.DataFrameModel):
    """Schema validato per output JOLTSAnalyzer."""
    series_date:       Series[pd.Timestamp]
    job_openings:      Series[float]  = pa.Field(ge=0.0, nullable=True)
    quits_rate:        Series[float]  = pa.Field(ge=0.0, le=10.0, nullable=True)
    openings_rate:     Series[float]  = pa.Field(ge=0.0, le=15.0, nullable=True)
    beveridge_gap:     Series[float]  = pa.Field(nullable=True)
    hires_quits_ratio: Series[float]  = pa.Field(ge=0.0, nullable=True)

    class Config:
        strict = False
        coerce = True


class ClaimsOutputSchema(pa.DataFrameModel):
    """Schema validato per output ClaimsCycleDetector."""
    week_ending:    Series[pd.Timestamp]
    initial_claims: Series[float]     = pa.Field(ge=0.0)
    claims_4wk_ma:  Series[float]     = pa.Field(ge=0.0)

    class Config:
        strict = False
        coerce = True


class PayrollOutputSchema(pa.DataFrameModel):
    """Schema validato per output PayrollDecomposer."""
    release_date:  Series[pd.Timestamp]
    sector:        Series[str]
    jobs_added_k:  Series[float] = pa.Field(nullable=True)

    class Config:
        strict = False
        coerce = True


@dataclass(frozen=True)
class ForecastBundle:
    """Previsione a un singolo orizzonte con intervallo di confidenza."""
    horizon:          Horizon
    target_metric:    str
    point_forecast:   float
    lower_10:         float
    upper_90:         float
    model_used:       str
    arima_forecast:   float
    ridge_forecast:   float
    ensemble_weight:  float


@dataclass(frozen=True)
class LabourForecastResult:
    """Risultato completo LabourForecastEngine per tutti gli orizzonti."""
    target_metric: str
    bundles:       tuple[ForecastBundle, ...]
    n_train_obs:   int
    arima_order:   tuple[int, int, int] | None
