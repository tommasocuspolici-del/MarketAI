"""Dataclass schemas per Valuation Engine.

Regola 9: ogni output ha schema validato.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

import numpy as np

__version__ = "1.0.0"
__all__ = ["PEMetrics", "ValuationLabel", "ValuationSignalResult", "ShillerCAPEPoint"]

ValuationLabel = Literal["deep_value", "cheap", "fair_value", "stretched", "bubble_warning"]
ERPRegime = Literal["attractive", "fair", "expensive", "extreme"]


@dataclass(frozen=True)
class PEMetrics:
    """Metriche P/E calcolate per un ticker in una data specifica.

    Attributes:
        metric_date:    Data di riferimento del calcolo.
        ticker:         Ticker (es. '^GSPC', 'SPY').
        price:          Prezzo di chiusura in USD.
        trailing_pe:    Price / EPS ultimi 4 trimestri.
        forward_pe:     Price / EPS forward 12M (stima consenso).
        shiller_cape:   Price / EPS reale media 10 anni (CPI-adjusted).
        peg_ratio:      Forward PE / tasso crescita EPS 5 anni (None se N/D).
        erp_implied:    Earnings Yield (1/ForwardPE) - Risk-Free Rate.
        erp_regime:     Classificazione ERP.
        eps_trailing_4q: Somma EPS ultimi 4 trimestri.
        eps_forward_1y:  EPS forward (stima).
        risk_free_rate:  DGS10 usato per ERP.
    """
    metric_date:     date
    ticker:          str
    price:           float
    trailing_pe:     float | None
    forward_pe:      float | None
    shiller_cape:    float | None
    peg_ratio:       float | None
    erp_implied:     float | None
    erp_regime:      str | None
    eps_trailing_4q: float | None
    eps_forward_1y:  float | None
    risk_free_rate:  float | None


@dataclass(frozen=True)
class ValuationSignalResult:
    """Output del ValuationSignalGenerator — segnale composito [-1, +1].

    Attributes:
        signal_date:       Data del segnale.
        ticker:            Ticker di riferimento.
        valuation_score:   Score composito [-1,+1]: +1=deep value, -1=bubble.
        trailing_pe_signal: Contributo trailing PE al score.
        forward_pe_signal:  Contributo forward PE al score.
        cape_signal:        Contributo CAPE al score.
        erp_signal:         Contributo ERP al score (invertito: ERP alto = bullish).
        label:              Label qualitativo.
        pe_metrics:         Metriche PE usate per il calcolo.
    """
    signal_date:         date
    ticker:              str
    valuation_score:     float
    trailing_pe_signal:  float
    forward_pe_signal:   float
    cape_signal:         float
    erp_signal:          float
    label:               ValuationLabel
    pe_metrics:          PEMetrics | None = None


@dataclass(frozen=True)
class ShillerCAPEPoint:
    """Singolo punto della serie storica CAPE Shiller."""
    data_date:        date
    sp500_price:      float | None
    eps_10y_real_avg: float | None
    cape_ratio:       float | None
    bond_yield:       float | None
    erp_implied:      float | None
