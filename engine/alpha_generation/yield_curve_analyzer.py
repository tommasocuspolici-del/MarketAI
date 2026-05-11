"""YieldCurveAnalyzer — Settimana 3 Roadmap Unificata.

Analizza la curva dei tassi e calcola la probabilità di recessione a 12 mesi
tramite il modello Estrella-Mishkin (1996).

Serie FRED usate:
  DGS10  — Treasury 10Y
  DGS2   — Treasury 2Y
  DGS3MO — Treasury 3M
  T10Y2Y — Spread 10Y-2Y (pre-calcolato da FRED)
  T10Y3M — Spread 10Y-3M (input primario modello E-M)
  T10YIE — Breakeven inflation 10Y (TIPS)
  FEDFUNDS — Fed Funds Rate effettivo

Regola 2 (SRP): solo analisi yield curve e probabilità recessione.
Regola 8: scipy.stats per la funzione di distribuzione normale.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from scipy.stats import norm

from engine.alpha_generation.schemas import CurveRegime, YieldCurveOutput
from shared.logger import get_logger

if TYPE_CHECKING:
    import pandas as pd

__version__ = "1.0.0"
__all__ = ["YieldCurveAnalyzer"]

log = get_logger(__name__)

# Parametri Estrella-Mishkin (1996), calibrati su dati NBER 1960-1995
# P(recession 12m) = Phi(alpha + beta * spread_10y_3m)
_EM_ALPHA = -0.6022
_EM_BETA  = -0.5517

# Soglie spread 10Y-2Y per regime curva
_SPREAD_INVERTED   = -0.50   # < -50 bps → inversione significativa
_SPREAD_FLAT       =  0.00   # tra -50 e 0 → flat/quasi-invertita
_SPREAD_STEEP      =  1.50   # > +150 bps → curva ripida


class YieldCurveAnalyzer:
    """Analizza la curva yield e calcola la probabilità di recessione a 12 mesi.

    Usage::

        analyzer = YieldCurveAnalyzer()
        output = analyzer.analyze(
            dgs10_df=dgs10_df, dgs2_df=dgs2_df, t10y3m_df=t10y3m_df,
            t10yie_df=t10yie_df,
        )
    """

    def analyze(
        self,
        dgs10_df:    pd.DataFrame,
        dgs2_df:     pd.DataFrame,
        dgs3mo_df:   pd.DataFrame | None = None,
        t10y2y_df:   pd.DataFrame | None = None,
        t10y3m_df:   pd.DataFrame | None = None,
        t10yie_df:   pd.DataFrame | None = None,
        fedfunds_df: pd.DataFrame | None = None,
    ) -> YieldCurveOutput:
        """Calcola regime curva e probabilità recessione Estrella-Mishkin.

        Args:
            dgs10_df:    DataFrame OHLCV-like con valore 10Y Treasury.
            dgs2_df:     DataFrame 2Y Treasury.
            dgs3mo_df:   DataFrame 3M Treasury (opzionale).
            t10y2y_df:   DataFrame spread 10Y-2Y pre-calcolato (opzionale).
            t10y3m_df:   DataFrame spread 10Y-3M (input E-M, preferito su calcolo).
            t10yie_df:   DataFrame breakeven inflation 10Y (opzionale).
            fedfunds_df: DataFrame Fed Funds Rate (opzionale).

        Returns:
            YieldCurveOutput con regime, recession_prob e score.
        """
        y_10y  = _latest_value(dgs10_df)
        y_2y   = _latest_value(dgs2_df)
        y_3m   = _latest_value(dgs3mo_df) if dgs3mo_df is not None else None
        be10y  = _latest_value(t10yie_df) if t10yie_df is not None else None
        _latest_value(fedfunds_df) if fedfunds_df is not None else None

        # Calcola spread 10Y-2Y (usa serie pre-calcolata se disponibile)
        spread_10y_2y: float | None
        if t10y2y_df is not None and not t10y2y_df.empty:
            spread_10y_2y = _latest_value(t10y2y_df)
        elif y_10y is not None and y_2y is not None:
            spread_10y_2y = y_10y - y_2y
        else:
            spread_10y_2y = None

        # Calcola spread 10Y-3M (input Estrella-Mishkin)
        spread_10y_3m: float | None
        if t10y3m_df is not None and not t10y3m_df.empty:
            spread_10y_3m = _latest_value(t10y3m_df)
        elif y_10y is not None and y_3m is not None:
            spread_10y_3m = y_10y - y_3m
        else:
            spread_10y_3m = None

        # Probabilità recessione 12m — modello Estrella-Mishkin (1996)
        recession_prob = self.recession_probability(spread_10y_3m)

        # Regime curva (basato su spread 10Y-2Y)
        curve_regime = self._classify_regime(spread_10y_2y)

        # Score: [-1, +1] in base a regime e recession prob
        score = self._compute_score(curve_regime, recession_prob, spread_10y_2y)

        inversion = spread_10y_2y is not None and spread_10y_2y < 0

        log.info(
            "yield_curve_analyzer.done",
            regime=curve_regime.value,
            score=round(score, 3),
            spread_10y_2y=round(spread_10y_2y, 3) if spread_10y_2y else None,
            spread_10y_3m=round(spread_10y_3m, 3) if spread_10y_3m else None,
            recession_prob=round(recession_prob, 3) if recession_prob else None,
        )

        return YieldCurveOutput(
            curve_regime=curve_regime,
            regime_score=score,
            recession_prob_12m=recession_prob,
            spread_10y_2y=spread_10y_2y,
            spread_10y_3m=spread_10y_3m,
            y_10y=y_10y,
            breakeven_10y=be10y,
            inversion_detected=inversion,
        )

    @staticmethod
    def recession_probability(spread_10y_3m: float | None) -> float | None:
        """Calcola P(recessione 12m) con il modello Estrella-Mishkin (1996).

        Formula: P = Phi(a + b * spread), dove:
          a = -0.6022, b = -0.5517
          Phi = funzione di distribuzione normale standard

        Il modello è calibrato con spread in punti percentuali (es. -0.5 per -50 bps).

        Args:
            spread_10y_3m: Spread 10Y-3M in punti percentuali (può essere negativo).

        Returns:
            Probabilità in [0, 1], o None se spread non disponibile.
        """
        if spread_10y_3m is None:
            return None
        z = _EM_ALPHA + _EM_BETA * float(spread_10y_3m)
        return float(norm.cdf(z))

    @staticmethod
    def _classify_regime(spread_10y_2y: float | None) -> CurveRegime:
        """Classifica il regime della curva yield.

        Args:
            spread_10y_2y: Spread 10Y-2Y in punti percentuali.

        Returns:
            CurveRegime enum.
        """
        if spread_10y_2y is None:
            return CurveRegime.NORMAL  # fallback conservativo

        if spread_10y_2y < _SPREAD_INVERTED:
            return CurveRegime.INVERTED
        if spread_10y_2y < _SPREAD_FLAT:
            return CurveRegime.FLAT
        if spread_10y_2y > _SPREAD_STEEP:
            return CurveRegime.STEEP
        return CurveRegime.NORMAL

    @staticmethod
    def _compute_score(
        regime:         CurveRegime,
        recession_prob: float | None,
        spread:         float | None,
    ) -> float:
        """Calcola il contributo numerico [-1, +1] al macro_score.

        Logica:
          - Curva invertita con alta prob. recessione → score fortemente negativo
          - Curva ripida → favorevole, score positivo
          - Incorpora recession_prob come fattore di intensità
        """
        # Score base per regime
        base: dict[CurveRegime, float] = {
            CurveRegime.STEEP:    0.6,
            CurveRegime.NORMAL:   0.2,
            CurveRegime.FLAT:    -0.3,
            CurveRegime.INVERTED:-0.8,
        }
        score = base[regime]

        # Modifica per recession probability
        if recession_prob is not None:
            # Alta prob recessione abbassa ulteriormente lo score
            # Low prob (< 10%) lo alza leggermente
            rec_adj = -(recession_prob - 0.15) * 0.5
            score = float(np.clip(score + rec_adj, -1.0, 1.0))

        return float(np.clip(score, -1.0, 1.0))


# ─── Helper ──────────────────────────────────────────────────────────────────

def _latest_value(df: pd.DataFrame | None) -> float | None:
    """Estrae l'ultimo valore non-NaN da un DataFrame macro."""
    if df is None or df.empty:
        return None
    col = "value" if "value" in df.columns else df.columns[-1]
    vals = df[col].dropna()
    if vals.empty:
        return None
    return float(vals.iloc[-1])
