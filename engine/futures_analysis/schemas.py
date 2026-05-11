"""Dataclass schemas per engine/futures_analysis.

Tutti i tipi di output sono frozen dataclass (immutabili).
Regola 3: type hints completi.
Regola 8: valori numerici come float (np.float64 nei calcoli interni).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


class TermStructure(StrEnum):
    """Forma della term structure futures (relazione front vs back month)."""
    BACKWARDATION = "backwardation"  # front > back: pressione immediata, segnale bullish
    FLAT          = "flat"           # front ≈ back: mercato neutro
    CONTANGO      = "contango"       # front < back: struttura normale per commodity


class OISignal(StrEnum):
    """Segnale Open Interest / Prezzo — 4 combinazioni (Schwager, 1984)."""
    TREND_CONFIRMED_BULLISH   = "trend_confirmed_bullish"   # OI↑ + prezzo↑
    DISTRIBUTION_BEARISH      = "distribution_bearish"      # OI↑ + prezzo↓
    SHORT_COVERING_WEAK_BUY   = "short_covering_weak_bullish"  # OI↓ + prezzo↑
    LIQUIDATION_POSSIBLE_BTM  = "liquidation_possible_bottom"  # OI↓ + prezzo↓
    INSUFFICIENT_DATA         = "insufficient_data"


class CommodityRegime(StrEnum):
    """Regime complessivo della commodity da combinazione segnali."""
    BULLISH          = "bullish"          # term structure + OI + basis favorevoli
    BEARISH          = "bearish"          # segnali negativi multipli
    NEUTRAL          = "neutral"          # segnali misti o assenti
    BACKWARDATION_SQUEEZE = "backwardation_squeeze"  # forte backwardation + OI in salita
    CONTANGO_TRAP    = "contango_trap"    # profondo contango + OI debole


@dataclass(frozen=True)
class RollYieldResult:
    """Output del RollAnalyzer.

    Attributes:
        ticker:             Simbolo futures (es. 'CL=F').
        computed_at:        Timestamp UTC.
        roll_yield_22d:     Roll yield su 22 giorni (≈ 1 mese lavorativo).
        roll_yield_annual:  Roll yield annualizzato (22d x 252/22).
        term_structure:     Forma della curva (BACKWARDATION/FLAT/CONTANGO).
        front_close:        Prezzo corrente front month.
        second_proxy:       Prezzo proxy second month (22 gg fa).
        roll_pct_rank:      Percentile rank del roll_yield su lookback storico.
        signal:             'bullish' | 'bearish' | 'neutral' (per OI overlay).
    """
    ticker:            str
    computed_at:       datetime
    roll_yield_22d:    float
    roll_yield_annual: float
    term_structure:    TermStructure
    front_close:       float
    second_proxy:      float
    roll_pct_rank:     float | None
    signal:            str   # 'bullish' | 'bearish' | 'neutral'


@dataclass(frozen=True)
class BasisResult:
    """Output del BasisAnalyzer.

    Attributes:
        ticker:         Simbolo futures.
        spot_ticker:    Simbolo ETF spot proxy (es. 'USO', 'GLD').
        computed_at:    Timestamp UTC.
        basis:          futures_close - spot_close (valore assoluto).
        basis_pct:      basis / spot_close * 100 (percentuale).
        basis_zscore:   Z-Score del basis rispetto alla sua storia recente.
        signal:         'convergence' | 'divergence' | 'neutral'.
    """
    ticker:       str
    spot_ticker:  str
    computed_at:  datetime
    basis:        float | None
    basis_pct:    float | None
    basis_zscore: float | None
    signal:       str   # 'convergence' | 'divergence' | 'neutral'


@dataclass(frozen=True)
class OpenInterestResult:
    """Output del OpenInterestAnalyzer.

    Attributes:
        ticker:         Simbolo futures.
        computed_at:    Timestamp UTC.
        oi_signal:      OISignal classificato (4 combinazioni OI/price).
        oi_current:     Open interest corrente (contratti).
        oi_change_pct:  Variazione OI su N barre (%).
        price_change_pct: Variazione prezzo su N barre (%).
        oi_pct_rank:    Percentile rank OI su lookback storico.
        institutional_bias: 'long_bias' | 'short_bias' | 'neutral'.
    """
    ticker:              str
    computed_at:         datetime
    oi_signal:           OISignal
    oi_current:          int | None
    oi_change_pct:       float | None
    price_change_pct:    float | None
    oi_pct_rank:         float | None
    institutional_bias:  str   # 'long_bias' | 'short_bias' | 'neutral'


@dataclass(frozen=True)
class CommodityAnalysis:
    """Output aggregato del CommodityRegimeClassifier.

    Combina roll_yield, basis e OI in un regime e score unico.

    Attributes:
        ticker:         Simbolo futures.
        computed_at:    Timestamp UTC.
        regime:         CommodityRegime classificato.
        score:          Score numerico [-1, +1] per composite signal.
        roll_result:    RollYieldResult di input.
        basis_result:   BasisResult di input.
        oi_result:      OpenInterestResult di input.
        confidence:     'HIGH' | 'MEDIUM' | 'LOW'.
        summary:        Testo descrittivo per UI.
    """
    ticker:       str
    computed_at:  datetime
    regime:       CommodityRegime
    score:        float
    roll_result:  RollYieldResult
    basis_result: BasisResult
    oi_result:    OpenInterestResult
    confidence:   str
    summary:      str
